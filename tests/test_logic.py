import datetime as dt

import pytest

from openrec.logic import (
    UTC,
    baseload_profile,
    build_event,
    current_flag,
    drop_short_windows,
    local_slot,
    parse_duration,
    quarter_starts,
    simple_value_at,
    surplus_flags,
)


def test_quarter_starts_normal_day_has_96_from_cet_midnight():
    q = quarter_starts(dt.date(2026, 10, 12))
    assert len(q) == 96
    assert q[0] == dt.datetime(2026, 10, 11, 22, 0, tzinfo=UTC)  # 00:00 CEST
    assert q[1] - q[0] == dt.timedelta(minutes=15)


@pytest.mark.parametrize("day,count", [(dt.date(2026, 10, 25), 100), (dt.date(2027, 3, 28), 92)])
def test_quarter_starts_dst_days(day, count):
    assert len(quarter_starts(day)) == count


def test_local_slot_uses_lisbon_time():
    # 12:00 UTC in October = 13:00 Lisbon (WEST)
    assert local_slot(dt.datetime(2026, 10, 12, 12, 0, tzinfo=UTC)) == 13 * 4


def test_drop_short_windows():
    assert drop_short_windows([0, 1, 0, 1, 1, 0, 1], 2) == [0, 0, 0, 1, 1, 0, 0]


def test_baseload_profile_median_and_default():
    t = dt.datetime(2026, 10, 12, 11, 0, tzinfo=UTC)  # 12:00 Lisbon, slot 48
    hist = {t: 0.2, t + dt.timedelta(days=1): 0.4, t + dt.timedelta(days=2): 1.0}
    prof = baseload_profile(hist, default_kw=0.3)
    assert prof[48] == 0.4
    assert prof[0] == 0.3


def _flags(forecast, prices=None, **kw):
    day = dt.date(2026, 10, 12)
    q = quarter_starts(day)
    fc = {t: forecast(t) for t in q}
    defaults = dict(pv_max_kw=3.0, threshold_kw=1.0, min_window_quarters=2, negative_price_windows=True)
    defaults.update(kw)
    return q, surplus_flags(q, fc, [0.3] * 96, prices or {}, **defaults)


def test_surplus_flags_midday_window_only():
    def fc(t):
        hour = t.astimezone(dt.timezone(dt.timedelta(hours=1))).hour  # Lisbon summer time
        return 2.5 if 11 <= hour < 15 else 0.2

    q, flags = _flags(fc)
    on_hours = {t.astimezone(dt.timezone(dt.timedelta(hours=1))).hour for t, f in zip(q, flags) if f}
    assert on_hours == {11, 12, 13, 14}
    assert sum(flags) == 16


def test_surplus_flags_caps_pv_at_inverter_limit():
    q, flags = _flags(lambda t: 10.0, pv_max_kw=1.2, threshold_kw=1.0)
    assert sum(flags) == 0  # 1.2 - 0.3 = 0.9 < 1.0


def test_surplus_flags_negative_price_opens_window_and_missing_forecast_is_safe():
    day = dt.date(2026, 10, 12)
    q = quarter_starts(day)
    prices = {q[10]: -1.0, q[11]: 0.0}
    flags = surplus_flags(q, dict.fromkeys(q, 0.0), [0.3] * 96, prices, pv_max_kw=3, threshold_kw=1, min_window_quarters=2,
                          negative_price_windows=True)
    assert flags[10:12] == [1, 1] and sum(flags) == 2
    flags_off = surplus_flags(q, {}, [0.3] * 96, prices, pv_max_kw=3, threshold_kw=1, min_window_quarters=2,
                              negative_price_windows=False)
    assert sum(flags_off) == 0


def test_build_event_shape_and_control_day_zeroes_simple():
    day = dt.date(2026, 10, 12)
    q = quarter_starts(day)
    prices = {t: 50.0 for t in q}
    flags = [1 if 40 <= i < 50 else 0 for i in range(len(q))]
    ev = build_event("p1", day, q, prices, flags, steering=True)
    assert ev["programID"] == "p1"
    assert ev["eventName"] == "open-rec 2026-10-12 steer"
    assert ev["intervalPeriod"] == {"start": "2026-10-11T22:00:00Z", "duration": "PT15M"}
    assert len(ev["intervals"]) == 96
    assert ev["intervals"][40]["payloads"] == [{"type": "PRICE", "values": [0.05]}, {"type": "SIMPLE", "values": [1]}]
    control = build_event("p1", day, q, prices, flags, steering=False)
    assert control["eventName"].endswith("control")
    assert all(i["payloads"][-1] == {"type": "SIMPLE", "values": [0]} for i in control["intervals"])


def test_parse_duration_variants():
    assert parse_duration("PT15M") == dt.timedelta(minutes=15)
    assert parse_duration("P0Y0M0DT1H0M0S") == dt.timedelta(hours=1)
    assert parse_duration("P1D") == dt.timedelta(days=1)
    with pytest.raises(ValueError):
        parse_duration("P1M")


def test_simple_value_at_and_current_flag():
    day = dt.date(2026, 10, 12)
    q = quarter_starts(day)
    flags = [1 if i == 50 else 0 for i in range(len(q))]
    flags[51] = 1
    ev = build_event("p1", day, q, {}, flags, steering=True)
    assert simple_value_at(ev, q[50] + dt.timedelta(minutes=7)) == 1
    assert simple_value_at(ev, q[52]) == 0
    assert simple_value_at(ev, q[0] - dt.timedelta(minutes=1)) is None
    assert current_flag([ev], q[51]) == 1
    assert current_flag([], q[51]) == 0  # no event -> off


def test_current_flag_most_recent_event_wins():
    day = dt.date(2026, 10, 12)
    q = quarter_starts(day)
    old = build_event("p1", day, q, {}, [1] * len(q), steering=True)
    old["modificationDateTime"] = "2026-10-11T10:00:00Z"
    new = build_event("p1", day, q, {}, [0] * len(q), steering=True)
    new["modificationDateTime"] = "2026-10-11T12:00:00Z"
    assert current_flag([old, new], q[10]) == 0
