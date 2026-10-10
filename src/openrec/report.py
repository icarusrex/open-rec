"""Estimate quarter-hour PV/load matching on steering and control market days.

Cumulative energy deltas are allocated by elapsed overlap assuming uniform power.
Sum(min(PV, consumption)) is a matching estimate, not physical self-consumption.
The paired mean and randomization test address magnitude; the sign test addresses
win frequency. Random pairing does not remove weather noise or thermal carryover.
"""

from __future__ import annotations

import datetime as dt
import math
import random
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from zoneinfo import ZoneInfo

from .logic import LOCAL_TZ, QUARTER, UTC, quarter_starts
from .testplan import is_steering_day, pair_of


def floor_quarter(ts: dt.datetime) -> dt.datetime:
    ts = ts.astimezone(UTC)
    return ts.replace(minute=ts.minute - ts.minute % 15, second=0, microsecond=0)


class EnergyIntervals(dict[dt.datetime, float]):
    """Energy estimates plus actual usable elapsed observation time per quarter."""

    def __init__(self):
        super().__init__()
        self.observed_seconds: dict[dt.datetime, float] = {}

    def covered_quarters(self) -> set[dt.datetime]:
        return {q for q, seconds in self.observed_seconds.items() if seconds >= 900 - 1e-6}


def interval_energy(
    snapshots: Iterable[tuple[dt.datetime, float]],
    *,
    max_gap: dt.timedelta = QUARTER + dt.timedelta(minutes=1),
) -> EnergyIntervals:
    """Allocate valid deltas by elapsed overlap, assuming uniform power within a sample.

    Gaps beyond a nominal 15-minute poll plus one minute jitter, counter resets,
    duplicate timestamps and invalid values are excluded. Partial quarters retain
    their energy but cannot count toward observed coverage or baseload estimates.
    """
    points = sorted((ts.astimezone(UTC), v) for ts, v in snapshots)
    out = EnergyIntervals()
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        delta = v1 - v0
        elapsed = (t1 - t0).total_seconds()
        if (not math.isfinite(v0) or not math.isfinite(v1) or v0 < 0 or delta < 0
                or elapsed <= 0 or elapsed > max_gap.total_seconds()):
            continue
        q = floor_quarter(t0)
        while q < t1:
            seconds = (min(t1, q + QUARTER) - max(t0, q)).total_seconds()
            out[q] = out.get(q, 0.0) + delta * seconds / elapsed
            out.observed_seconds[q] = out.observed_seconds.get(q, 0.0) + seconds
            q += QUARTER
    return out


@dataclass(frozen=True)
class DayMetrics:
    day: dt.date
    pv_kwh: float
    house_kwh: float
    self_consumed_kwh: float
    coverage: float = 1.0

    @property
    def ratio(self) -> float:
        return self.self_consumed_kwh / self.pv_kwh if self.pv_kwh > 0 else 0.0


def daily_metrics(
    pv_q: Mapping[dt.datetime, float],
    house_q: Mapping[dt.datetime, float],
    tz: ZoneInfo = LOCAL_TZ,
    min_coverage: float = 0.9,
    now: dt.datetime | None = None,
) -> list[DayMetrics]:
    """Per local day; days with less than ``min_coverage`` of quarters present are dropped."""
    days: dict[dt.date, list[tuple[float, float]]] = {}
    usable = set(pv_q) & set(house_q)
    for values in (pv_q, house_q):
        if isinstance(values, EnergyIntervals):
            usable &= values.covered_quarters()
    for q in usable:
        if not all(math.isfinite(v) and v >= 0 for v in (pv_q[q], house_q[q])):
            continue
        days.setdefault(q.astimezone(tz).date(), []).append((pv_q[q], house_q[q]))
    out = []
    for day, rows in sorted(days.items()):
        quarters = quarter_starts(day, tz)
        if now is not None and now < quarters[-1] + QUARTER:
            continue
        if len(rows) < len(quarters) * min_coverage:
            continue
        pv = sum(p for p, _ in rows)
        house = sum(h for _, h in rows)
        self_consumed = sum(min(p, h) for p, h in rows)
        out.append(DayMetrics(day, pv, house, self_consumed, len(rows) / len(quarters)))
    return out


@dataclass(frozen=True)
class Summary:
    pairs: int
    mean_paired_diff: float | None  # steering ratio minus control ratio, mean over complete pairs
    paired_diffs: list[float]
    bands: list[tuple[str, int, float | None, int, float | None]]  # label, n_on, mean_on, n_off, mean_off

    @property
    def improved_pairs(self) -> int:
        return sum(1 for d in self.paired_diffs if d > 0)

    @property
    def sign_test_p(self) -> float | None:
        return sign_test_p(self.paired_diffs)

    @property
    def mean_test_p(self) -> float | None:
        return mean_randomization_p(self.paired_diffs)


def sign_test_p(diffs: Sequence[float]) -> float | None:
    """Exact two-sided sign test: how surprising is this many improved pairs if steering did nothing?

    Ties (zero differences) are dropped. No distribution assumptions, so it suits
    a small number of noisy pairs.
    """
    nonzero = [d for d in diffs if d != 0]
    n = len(nonzero)
    if n == 0:
        return None
    k = sum(1 for d in nonzero if d > 0)
    tail = sum(math.comb(n, i) for i in range(min(k, n - k) + 1)) / 2**n
    return min(1.0, 2 * tail)


def mean_randomization_p(diffs: Sequence[float], resamples: int = 20000) -> float | None:
    """Two-sided within-pair sign-flip test of the mean under the sharp null.

    Exact through 16 pairs; deterministic Monte Carlo thereafter. This assumes
    random assignment without carryover/interference and does not cure bad data.
    """
    if not diffs:
        return None
    observed = abs(sum(diffs))
    tolerance = 1e-12
    if len(diffs) <= 16:
        extreme = sum(abs(sum(s * d for s, d in zip(signs, diffs))) >= observed - tolerance
                      for signs in product((-1, 1), repeat=len(diffs)))
        return extreme / 2**len(diffs)
    rng = random.Random(0)
    extreme = sum(abs(sum(rng.choice((-1, 1)) * d for d in diffs)) >= observed - tolerance
                  for _ in range(resamples))
    return (extreme + 1) / (resamples + 1)


def compare(days: Sequence[DayMetrics], start: dt.date, seed: str) -> Summary:
    plan_days = [d for d in days if d.day >= start and d.pv_kwh > 0]
    by_pair: dict[int, dict[bool, DayMetrics]] = {}
    for d in plan_days:
        by_pair.setdefault(pair_of(d.day, start), {})[is_steering_day(d.day, start, seed)] = d
    diffs = [p[True].ratio - p[False].ratio for p in by_pair.values() if True in p and False in p]

    bands = []
    if plan_days:
        yields = sorted(d.pv_kwh for d in plan_days)
        cuts = [yields[len(yields) // 3], yields[2 * len(yields) // 3]]
        labels = ["low PV", "mid PV", "high PV"]
        for b, label in enumerate(labels):
            lo = cuts[b - 1] if b > 0 else float("-inf")
            hi = cuts[b] if b < 2 else float("inf")
            members = [d for d in plan_days if lo <= d.pv_kwh < hi]
            on = [d.ratio for d in members if is_steering_day(d.day, start, seed)]
            off = [d.ratio for d in members if not is_steering_day(d.day, start, seed)]
            bands.append(
                (label, len(on), statistics.mean(on) if on else None, len(off), statistics.mean(off) if off else None)
            )
    return Summary(len(diffs), statistics.mean(diffs) if diffs else None, diffs, bands)


def format_summary(summary: Summary) -> str:
    def pct(x: float | None) -> str:
        return "n/a" if x is None else f"{x * 100:.1f}%"

    lines = [
        f"Complete on/off pairs: {summary.pairs}",
        "Mean paired difference in self-consumption ratio (steer - control): "
        + ("n/a" if summary.mean_paired_diff is None else f"{summary.mean_paired_diff * 100:+.1f} pp"),
        'Within-pair randomization test of mean (two-sided): '
        + ('n/a' if summary.mean_test_p is None else f'p = {summary.mean_test_p:.4f}')
        + ('; Monte Carlo, 20,000 draws' if summary.pairs > 16 else '; exact'),
        "Pairs where steering did better: "
        + f"{summary.improved_pairs} of {summary.pairs}"
        + ("" if summary.sign_test_p is None else f" (sign test, two-sided p = {summary.sign_test_p:.3f})"),
        "",
        f"{'PV yield band':<14}{'steer days':>11}{'steer ratio':>13}{'control days':>14}{'control ratio':>15}",
    ]
    for label, n_on, m_on, n_off, m_off in summary.bands:
        lines.append(f"{label:<14}{n_on:>11}{pct(m_on):>13}{n_off:>14}{pct(m_off):>15}")
    if summary.pairs < 10:
        lines.append("")
        lines.append("Fewer than 10 pairs: treat the difference as indicative, not conclusive.")
    lines.extend(['', 'Metric: quarter-hour energy matching estimate, not measured physical self-consumption.',
                  'Tank heat can carry over into control days; neither statistical test removes carryover.'])
    return "\n".join(lines)


def format_daily(days: Sequence[DayMetrics], start: dt.date, seed: str) -> str:
    lines = ['Market day  Assigned  PV kWh  House kWh  Matched kWh  Match ratio  Coverage']
    for day in days:
        assigned = 'steer' if is_steering_day(day.day, start, seed) else 'control'
        lines.append(f'{day.day}  {assigned:<8}  {day.pv_kwh:6.2f}  {day.house_kwh:9.2f}  '
                     f'{day.self_consumed_kwh:11.2f}  {day.ratio:10.1%}  {day.coverage:8.1%}')
    return '\n'.join(lines)
