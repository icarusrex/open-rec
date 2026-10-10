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


def test_interval_energy_excludes_long_gaps_and_skips_resets():
    t0 = dt.datetime(2026, 10, 12, 10, 0, 20, tzinfo=UTC)
    snaps = [
        (t0, 100.0),
        (t0 + dt.timedelta(minutes=15), 100.5),
        (t0 + dt.timedelta(minutes=45), 101.5),  # one missed sample
        (t0 + dt.timedelta(minutes=60), 0.2),  # counter reset
    ]
    e = interval_energy(snaps)
    q0 = dt.datetime(2026, 10, 12, 10, 0, tzinfo=UTC)
    assert e[q0] == pytest.approx(0.5 * 880 / 900)
    assert e[q0 + dt.timedelta(minutes=15)] == pytest.approx(0.5 * 20 / 900)
    assert q0 + dt.timedelta(minutes=30) not in e
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


def test_interval_energy_keeps_energy_from_two_snapshots_in_one_quarter():
    t = dt.datetime(2026, 10, 12, 10, 0, 20, tzinfo=UTC)
    snaps = [(t, 10.0), (t + dt.timedelta(minutes=5), 10.1), (t + dt.timedelta(minutes=15), 10.3)]
    e = interval_energy(snaps)
    assert sum(e.values()) == pytest.approx(0.3)
    assert e[dt.datetime(2026, 10, 12, 10, 0, tzinfo=UTC)] == pytest.approx(0.1 + 0.2 * 580 / 600)


def test_counter_delta_is_allocated_by_elapsed_overlap():
    t = dt.datetime(2026, 10, 12, 12, 14, tzinfo=UTC)
    e = interval_energy([(t, 0), (t + dt.timedelta(minutes=2), 2)])
    assert e[floor(t)] == pytest.approx(1)
    assert e[floor(t) + dt.timedelta(minutes=15)] == pytest.approx(1)


def floor(t):
    return t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0)


def test_two_daily_snapshots_do_not_manufacture_coverage():
    t = dt.datetime(2026, 10, 12, tzinfo=UTC)
    e = interval_energy([(t, 0), (t + dt.timedelta(days=1), 4)])
    assert daily_metrics(e, e) == []


def test_partial_quarters_do_not_count_as_observed_coverage():
    t = dt.datetime(2026, 10, 12, tzinfo=UTC)
    snaps = []
    for i in range(96):
        q = t + dt.timedelta(minutes=15 * i)
        snaps.extend([(q, float(i)), (q + dt.timedelta(seconds=30), i + 0.1)])
    e = interval_energy(snaps, max_gap=dt.timedelta(minutes=1))
    assert daily_metrics(e, e) == []


def test_fall_dst_coverage_uses_100_quarters():
    from openrec.logic import MARKET_TZ, quarter_starts

    qs = quarter_starts(dt.date(2026, 10, 25))
    partial = dict.fromkeys(qs[:89], 1.0)
    assert daily_metrics(partial, partial, tz=MARKET_TZ) == []


def test_current_unfinished_market_day_is_excluded():
    from openrec.logic import MARKET_TZ, quarter_starts

    qs = quarter_starts(dt.date(2026, 10, 12))
    partial = dict.fromkeys(qs[:90], 1.0)
    assert daily_metrics(partial, partial, tz=MARKET_TZ, now=qs[90]) == []


def test_mean_randomization_test_differs_from_win_count_test():
    from openrec import report

    diffs = [0.01] * 19 + [-0.5]
    assert report.sign_test_p(diffs) < 0.001
    assert report.mean_randomization_p(diffs) > 0.5
    assert report.mean_randomization_p([0.1] * 10) == pytest.approx(2 / 1024)


def test_daily_table_includes_assignment_and_coverage():
    from openrec import report

    day = DayMetrics(dt.date(2026, 10, 12), 5, 8, 3, 0.95)
    text = report.format_daily([day], day.day, 's')
    assert '2026-10-12' in text and '95.0%' in text and '60.0%' in text
