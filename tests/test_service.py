import dataclasses
import datetime as dt

import pytest

from openrec import service
from openrec.config import Settings
from openrec.logic import UTC, local_slot

NOW = dt.datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def counters(kw_by_quarter_index, days=3):
    """Cumulative kWh snapshots: constant kW per quarter, with given overrides by local slot."""
    snaps, total = [], 0.0
    t = NOW - dt.timedelta(days=days)
    while t <= NOW:
        snaps.append((t, total))
        total += kw_by_quarter_index(t) / 4
        t += dt.timedelta(minutes=15)
    return snaps


def test_baseload_subtracts_steered_load(monkeypatch):
    noon = local_slot(dt.datetime(2026, 10, 12, 12, 0, tzinfo=UTC))
    house = counters(lambda t: 3.3 if local_slot(t) == noon else 0.3)  # heater (3 kW) ran at that slot
    heater = counters(lambda t: 3.0 if local_slot(t) == noon else 0.0)
    data = {"sensor.house": house, "sensor.heater": heater}
    monkeypatch.setattr(service.db, "load_readings", lambda conn, entity, s, e: data[entity])

    base = dataclasses.replace(
        Settings.from_env(), ha_house_energy_entity="sensor.house", ha_steered_energy_entity=None
    )
    assert service.baseload_from_history(None, base, NOW)[noon] == pytest.approx(3.3)

    fixed = dataclasses.replace(base, ha_steered_energy_entity="sensor.heater")
    profile = service.baseload_from_history(None, fixed, NOW)
    assert profile[noon] == pytest.approx(0.3)
    assert profile[noon + 4] == pytest.approx(0.3)


def test_baseload_default_without_meter():
    s = dataclasses.replace(Settings.from_env(), ha_house_energy_entity=None, baseload_kw_default=0.4)
    assert service.baseload_from_history(None, s, NOW) == [0.4] * 96


def test_due_days_follow_the_market_day_and_publish_time():
    publish = dt.time(14, 30)
    none_done = lambda d: False  # noqa: E731
    # 10:00 Lisbon (WEST, UTC+1): only today's market day
    assert service.due_days(dt.datetime(2026, 10, 12, 9, 0, tzinfo=UTC), publish, none_done) == [dt.date(2026, 10, 12)]
    # 15:00 Lisbon: today and tomorrow
    assert service.due_days(dt.datetime(2026, 10, 12, 14, 0, tzinfo=UTC), publish, none_done) == [
        dt.date(2026, 10, 12),
        dt.date(2026, 10, 13),
    ]
    # 23:30 Lisbon = 00:30 Madrid: the current market day is already the 13th
    # and the 14th must NOT be due yet: OMIE only publishes it on the 13th at ~13:00 CET
    late = dt.datetime(2026, 10, 12, 22, 30, tzinfo=UTC)
    assert service.due_days(late, publish, lambda d: d == dt.date(2026, 10, 13)) == []
    assert service.due_days(late, publish, none_done) == [dt.date(2026, 10, 13)]
    # next afternoon the 14th becomes due
    assert service.due_days(dt.datetime(2026, 10, 13, 13, 31, tzinfo=UTC), publish, lambda d: d == dt.date(2026, 10, 13)) == [
        dt.date(2026, 10, 14)
    ]


class _FakeVtn:
    def __init__(self):
        self.upserts, self.pruned = [], []

    def ensure_program(self, name):
        return "p1"

    def upsert_event(self, body, prefix):
        self.upserts.append(body)
        return {"id": "e1"}

    def prune_events(self, program_id, keep_from):
        self.pruned.append(keep_from)
        return 0


def _patch_db(monkeypatch, store):
    monkeypatch.setattr(service.db, "save_prices", lambda c, p: store["prices"].update(p))
    monkeypatch.setattr(service.db, "save_forecast", lambda c, f: store["forecast"].update(f))
    monkeypatch.setattr(service.db, "load_prices", lambda c, s, e: dict(store["prices"]))
    monkeypatch.setattr(service.db, "load_forecast", lambda c, s, e: dict(store["forecast"]))
    monkeypatch.setattr(service.db, "load_readings", lambda *a: [])
    monkeypatch.setattr(service.db, "mark_published", lambda *a: store["marked"].append(a[1]))


def test_publish_without_forecast_is_a_safe_placeholder_and_not_marked(monkeypatch):
    from openrec.logic import quarter_starts

    store = {"prices": {}, "forecast": {}, "marked": []}
    _patch_db(monkeypatch, store)
    settings = dataclasses.replace(Settings.from_env(), ha_house_energy_entity=None, test_plan_start=None)
    vtn = _FakeVtn()
    day = dt.date(2026, 10, 12)

    def no_forecast(_):
        raise ConnectionError("open-meteo down")

    summary = service.publish_day(settings, None, vtn, day, prices_fetcher=lambda d: {}, forecast_fetcher=no_forecast)
    assert summary["complete"] is False and summary["window_quarters"] == 0
    assert store["marked"] == []
    assert all(i["payloads"][-1]["values"] == [0] for i in vtn.upserts[0]["intervals"])

    full = {q: 2.5 for q in quarter_starts(day)}
    summary = service.publish_day(settings, None, vtn, day, prices_fetcher=lambda d: {}, forecast_fetcher=lambda s: full)
    assert summary["complete"] is True and store["marked"] == [day]
    assert vtn.pruned[-1] == "2026-10-05"
