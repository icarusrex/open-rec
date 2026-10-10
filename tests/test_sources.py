import datetime as dt

import httpx
import pytest
import respx
from argon2 import PasswordHasher

from openrec.bootstrap import BL_SCOPES, bootstrap_sql
from openrec.logic import UTC, quarter_starts
from openrec.sources.forecast import OPEN_METEO_URL, fetch_pv_forecast, gti_to_kw
from openrec.sources.homeassistant import HomeAssistant
from openrec.sources.omie import map_quarters


def test_omie_map_quarters_matches_market_day_and_rejects_wrong_length():
    day = dt.date(2026, 10, 25)  # DST end: 100 quarters
    values = list(range(100))
    mapped = map_quarters(day, values)
    assert list(mapped) == quarter_starts(day)
    with pytest.raises(ValueError):
        map_quarters(day, values[:96])


def test_gti_to_kw_caps_and_floors():
    assert gti_to_kw(1000, 2.7, 0.85, 3.0) == pytest.approx(2.295)
    assert gti_to_kw(2000, 2.7, 1.0, 3.0) == 3.0
    assert gti_to_kw(None, 2.7, 0.85, 3.0) == 0.0


@respx.mock
def test_open_meteo_forecast_shifts_to_interval_start():
    route = respx.get(OPEN_METEO_URL).mock(
        return_value=httpx.Response(
            200,
            json={"minutely_15": {"time": ["2026-10-12T12:15", "2026-10-12T12:30"], "global_tilted_irradiance": [800, None]}},
        )
    )
    fc = fetch_pv_forecast(39.9, -8.6, 30, 0, 2.7, 0.85, 3.0)
    assert route.called
    params = route.calls[0].request.url.params
    assert params["minutely_15"] == "global_tilted_irradiance" and params["azimuth"] == "0"
    assert fc[dt.datetime(2026, 10, 12, 12, 0, tzinfo=UTC)] == pytest.approx(0.8 * 2.7 * 0.85)
    assert fc[dt.datetime(2026, 10, 12, 12, 15, tzinfo=UTC)] == 0.0


@respx.mock
def test_home_assistant_state_and_switch():
    respx.get("http://ha:8123/api/states/sensor.pv").mock(return_value=httpx.Response(200, json={"state": "123.4"}))
    respx.get("http://ha:8123/api/states/sensor.bad").mock(return_value=httpx.Response(200, json={"state": "unavailable"}))
    on = respx.post("http://ha:8123/api/services/input_boolean/turn_on").mock(return_value=httpx.Response(200, json=[]))
    ha = HomeAssistant("http://ha:8123/", "tok")
    assert ha.state("sensor.pv") == 123.4
    assert ha.state("sensor.bad") is None
    ha.set_on("input_boolean.open_rec_surplus_window", True)
    req = on.calls[0].request
    assert req.headers["Authorization"] == "Bearer tok"
    assert b"input_boolean.open_rec_surplus_window" in req.content


def test_bootstrap_sql_hashes_secrets_verifiably():
    sql = bootstrap_sql("bl", "bl-secret", "ven", "ven-secret")
    assert "bl-secret" not in sql and "ven-secret" not in sql
    line = [ln for ln in sql.splitlines() if "user_credentials" in ln][0]
    stored = line.split(", '")[-1].split("')")[0]
    assert PasswordHasher().verify(stored, "bl-secret")
    assert all(s in sql for s in BL_SCOPES)
