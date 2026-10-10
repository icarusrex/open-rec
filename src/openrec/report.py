"""Measure the effect of steering: self-consumption on steering days vs control days.

Inputs are cumulative energy counters (kWh totals) sampled every ~15 minutes
from Home Assistant: one for PV production, one for whole-house consumption.

Per 15-minute interval, self-consumed energy = min(PV, consumption).
Per day, self-consumption ratio = self-consumed / PV produced.

The headline number is the mean paired difference (steering day minus control
day of the same pair), which cancels most of the seasonal and weather trend.
A second view groups days into terciles of PV yield.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from .logic import LOCAL_TZ, QUARTER, UTC
from .testplan import is_steering_day, pair_of


def floor_quarter(ts: dt.datetime) -> dt.datetime:
    ts = ts.astimezone(UTC)
    return ts.replace(minute=ts.minute - ts.minute % 15, second=0, microsecond=0)


def interval_energy(snapshots: Iterable[tuple[dt.datetime, float]]) -> dict[dt.datetime, float]:
    """kWh per 15-minute interval from cumulative counter snapshots.

    A delta spanning several quarters is spread evenly over them; two snapshots
    in the same quarter (e.g. after a restart) count toward that quarter.
    Negative deltas (counter reset) are skipped.
    """
    points = sorted((ts.astimezone(UTC), v) for ts, v in snapshots)
    out: dict[dt.datetime, float] = {}
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        delta = v1 - v0
        if delta < 0:
            continue
        q0 = floor_quarter(t0)
        n = max(int((floor_quarter(t1) - q0) / QUARTER), 1)
        t0 = q0
        for k in range(n):
            q = t0 + QUARTER * k
            out[q] = out.get(q, 0.0) + delta / n
    return out


@dataclass(frozen=True)
class DayMetrics:
    day: dt.date
    pv_kwh: float
    house_kwh: float
    self_consumed_kwh: float

    @property
    def ratio(self) -> float:
        return self.self_consumed_kwh / self.pv_kwh if self.pv_kwh > 0 else 0.0


def daily_metrics(
    pv_q: Mapping[dt.datetime, float],
    house_q: Mapping[dt.datetime, float],
    tz: ZoneInfo = LOCAL_TZ,
    min_coverage: float = 0.9,
) -> list[DayMetrics]:
    """Per local day; days with less than ``min_coverage`` of quarters present are dropped."""
    days: dict[dt.date, list[tuple[float, float]]] = {}
    for q in set(pv_q) & set(house_q):
        days.setdefault(q.astimezone(tz).date(), []).append((pv_q[q], house_q[q]))
    out = []
    for day, rows in sorted(days.items()):
        if len(rows) < 96 * min_coverage:
            continue
        pv = sum(p for p, _ in rows)
        house = sum(h for _, h in rows)
        self_consumed = sum(min(p, h) for p, h in rows)
        out.append(DayMetrics(day, pv, house, self_consumed))
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
    return "\n".join(lines)
