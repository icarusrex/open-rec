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
