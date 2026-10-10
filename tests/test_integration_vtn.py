"""End-to-end against a live openleadr-rs VTN and Postgres.

Enable with:
  OPENREC_TEST_VTN_URL=http://localhost:3000
  OPENREC_TEST_VTN_DATABASE_URL=postgresql://openadr@localhost:5432/openadr   (to create test clients)
  OPENREC_TEST_DATABASE_URL=postgresql://openadr@localhost:5432/openrec_test
Home Assistant is mocked; OMIE and Open-Meteo are replaced by fixture data.
"""

import dataclasses
import datetime as dt
import os
import uuid

import httpx
import pytest
import respx

from openrec import db
from openrec.bootstrap import bootstrap_sql
from openrec.config import Settings
from openrec.logic import quarter_starts
from openrec.service import publish_day
from openrec.sources.homeassistant import HomeAssistant
from openrec.ven import Bridge
from openrec.vtn import VtnClient

VTN_URL = os.environ.get("OPENREC_TEST_VTN_URL")
VTN_DB = os.environ.get("OPENREC_TEST_VTN_DATABASE_URL")
APP_DB = os.environ.get("OPENREC_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(not (VTN_URL and VTN_DB and APP_DB), reason="live VTN not configured")

DAY = dt.date(2026, 10, 12)
QUARTERS = quarter_starts(DAY)
WINDOW = range(44, 56)  # 11:00-14:00 CEST


def fixture_prices(day):
    return {q: (-5.0 if i == 60 else 80.0) for i, q in enumerate(quarter_starts(day))}


def fixture_forecast(_settings):
    return {q: (2.5 if i in WINDOW else 0.1) for i, q in enumerate(QUARTERS)}


@pytest.fixture()
def env():
    suffix = uuid.uuid4().hex[:8]
    ids = {"bl": f"test-bl-{suffix}", "ven": f"test-ven-{suffix}"}
    with db.connect(VTN_DB) as conn:
        conn.execute(bootstrap_sql(ids["bl"], "bl-secret", ids["ven"], "ven-secret"))
    settings = dataclasses.replace(
        Settings.from_env(),
        database_url=APP_DB,
        vtn_url=VTN_URL,
        bl_client_id=ids["bl"],
        bl_client_secret="bl-secret",
        program_name=f"open-rec-test-{suffix}",
        ven_client_id=ids["ven"],
        ven_client_secret="ven-secret",
        ven_name=f"home-{suffix}",
        ha_house_energy_entity=None,
        ha_pv_energy_entity=None,
        test_plan_start=None,
        surplus_threshold_kw=1.0,
        baseload_kw_default=0.3,
        min_window_quarters=2,
        negative_price_windows=True,
    )
    conn = db.connect(APP_DB)
    db.init_schema(conn)
    conn.execute("TRUNCATE prices, pv_forecast, readings, published_events")
    yield settings, conn
    conn.close()


def test_publish_then_ven_follows(env):
    settings, conn = env
    bl = VtnClient(settings.vtn_url, settings.bl_client_id, settings.bl_client_secret)

    summary = publish_day(settings, conn, bl, DAY, prices_fetcher=fixture_prices, forecast_fetcher=fixture_forecast)
    assert summary["window_quarters"] == len(WINDOW)  # the lone negative-price quarter is dropped (min 2)
    assert summary["prices"] == 96 and summary["steering"] is True

    # Publishing again replaces the day's event instead of adding a second one
    publish_day(settings, conn, bl, DAY, prices_fetcher=fixture_prices, forecast_fetcher=fixture_forecast)
    program_id = bl.find_program_id(settings.program_name)
    events = bl.events(program_id)
    assert len(events) == 1
    stored = events[0]
    assert stored["eventName"] == "open-rec 2026-10-12 steer"
    assert len(stored["intervals"]) == 96
    assert stored["intervals"][44]["payloads"][-1] == {"type": "SIMPLE", "values": [1]}
    assert stored["intervals"][44]["payloads"][0] == {"type": "PRICE", "values": [0.08]}

    # The VEN registers itself, reads the event and drives the HA helper
    ven = VtnClient(settings.vtn_url, settings.ven_client_id, settings.ven_client_secret)
    assert ven.ensure_ven(settings.ven_name) == ven.ensure_ven(settings.ven_name)
    with respx.mock(assert_all_called=False) as mock:
        mock.route(host="localhost").pass_through()
        mock.route(host="127.0.0.1").pass_through()
        on = mock.post("http://ha:8123/api/services/input_boolean/turn_on").mock(return_value=httpx.Response(200, json=[]))
        off = mock.post("http://ha:8123/api/services/input_boolean/turn_off").mock(return_value=httpx.Response(200, json=[]))
        bridge = Bridge(ven, HomeAssistant("http://ha:8123", "tok"), "input_boolean.open_rec_surplus_window",
                        settings.program_name)
        assert bridge.tick(QUARTERS[43]) == 0
        assert bridge.tick(QUARTERS[44] + dt.timedelta(minutes=3)) == 1
        assert bridge.tick(QUARTERS[56]) == 0
        assert off.call_count == 2 and on.call_count == 1


def test_control_day_publishes_all_zero(env):
    settings, conn = env
    settings = dataclasses.replace(settings, test_plan_start=DAY, test_plan_seed="pick")
    from openrec.testplan import is_steering_day

    # find a control day in the first pair
    day = DAY if not is_steering_day(DAY, DAY, "pick") else DAY + dt.timedelta(days=1)
    bl = VtnClient(settings.vtn_url, settings.bl_client_id, settings.bl_client_secret)
    summary = publish_day(settings, conn, bl, day, prices_fetcher=fixture_prices,
                          forecast_fetcher=lambda s: {q: 2.5 for q in quarter_starts(day)})
    assert summary["steering"] is False
    events = bl.events(bl.find_program_id(settings.program_name))
    (ev,) = [e for e in events if e["eventName"].startswith(f"open-rec {day.isoformat()}")]
    assert ev["eventName"].endswith("control")
    assert all(i["payloads"][-1]["values"] == [0] for i in ev["intervals"])


def test_wrong_secret_is_rejected():
    bad = VtnClient(VTN_URL, "nobody", "wrong")
    with pytest.raises(httpx.HTTPStatusError):
        bad.programs()
