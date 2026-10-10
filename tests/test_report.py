import datetime as dt

import pytest

from openrec.logic import LOCAL_TZ, UTC
from openrec.report import (
    DayMetrics,
    compare,
    daily_metrics,
    format_summary,
    interval_energy,
)
from openrec.testplan import is_steering_day


def test_interval_energy_spreads_gaps_and_skips_resets():
    t0 = dt.datetime(2026, 10, 12, 10, 0, 20, tzinfo=UTC)
    snaps = [
        (t0, 100.0),
        (t0 + dt.timedelta(minutes=15), 100.5),
        (t0 + dt.timedelta(minutes=45), 101.5),  # one missed sample
        (t0 + dt.timedelta(minutes=60), 0.2),  # counter reset
    ]
    e = interval_energy(snaps)
    q0 = dt.datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
    assert e[q0] == pytest.approx(0.5)
    assert e[q0 + dt.timedelta(minutes=15)] == pytest.approx(0.5)
    assert e[q0 + dt.timedelta(minutes=30)] == pytest.approx(0.5)
    assert q0 + dt.timedelta(minutes=45) not in e


def _day(day, pv_mid, house_mid):
    """96 quarters: PV only 10:00-14:00 local, flat house load."""
    pv, house = {}, {}
    start = dt.datetime.combine(day, dt.time(0), LOCAL_TZ).astimezone(UTC)
    for i in range(96):
        q = start + dt.timedelta(minutes=15 * i)
        pv[q] = pv_mid if 40 <= i < 56 else 0.0
        house[q] = house_mid if 40 <= i < 56 else 0.1
    return pv, house


def test_daily_metrics_self_consumption():
    pv, house = _day(dt.date(2026, 10, 12), 0.5, 0.2)
    (m,) = daily_metrics(pv, house)
    assert m.pv_kwh == pytest.approx(8.0)
    assert m.self_consumed_kwh == pytest.approx(16 * 0.2)
    assert m.ratio == pytest.approx(0.4)


def test_daily_metrics_drops_incomplete_days():
    pv, house = _day(dt.date(2026, 10, 12), 0.5, 0.2)
    for q in list(pv)[:20]:
        del pv[q]
    assert daily_metrics(pv, house) == []


def test_compare_recovers_known_effect_despite_seasonal_trend():
    start = dt.date(2027, 1, 4)
    days = []
    for i in range(40):
        day = start + dt.timedelta(days=i)
        base = 0.30 + 0.004 * i  # season: ratio drifts up regardless of steering
        effect = 0.10 if is_steering_day(day, start, "s") else 0.0
        days.append(DayMetrics(day, pv_kwh=5 + i * 0.1, house_kwh=8, self_consumed_kwh=(5 + i * 0.1) * (base + effect)))
    s = compare(days, start, "s")
    assert s.pairs == 20
    # paired difference = effect +/- one day of drift (0.004)
    assert s.mean_paired_diff == pytest.approx(0.10, abs=0.005)
    assert len(s.bands) == 3
    text = format_summary(s)
    assert "Complete on/off pairs: 20" in text and " pp" in text


def test_sign_test_p_values():
    from openrec.report import sign_test_p

    assert sign_test_p([0.01] * 10) == pytest.approx(2 / 1024)
    assert sign_test_p([0.01] * 5 + [-0.01] * 5) == 1.0
    assert sign_test_p([0.01] * 15 + [-0.01] * 5) == pytest.approx(0.04139, abs=1e-4)
    assert sign_test_p([0.0, 0.0]) is None
