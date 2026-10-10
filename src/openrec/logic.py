"""Pure event logic: turn a PV forecast, a baseload profile and prices into an
OpenADR 3 event of 15-minute intervals, and read the current flag back out.

No I/O here, so everything is unit-testable.

Payloads per interval:
  PRICE  - OMIE Portuguese day-ahead price, EUR/kWh (informational)
  SIMPLE - 1 = surplus window (run flexible loads now), 0 = normal
"""

from __future__ import annotations

import datetime as dt
import re
import statistics
from collections.abc import Mapping, Sequence
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc
QUARTER = dt.timedelta(minutes=15)
MARKET_TZ = ZoneInfo("Europe/Madrid")  # OMIE market day runs on CET/CEST
LOCAL_TZ = ZoneInfo("Europe/Lisbon")


def quarter_starts(day: dt.date, tz: ZoneInfo = MARKET_TZ) -> list[dt.datetime]:
    """UTC start of every 15-minute interval of a local day (92, 96 or 100 on DST days)."""
    start = dt.datetime.combine(day, dt.time(0), tz).astimezone(UTC)
    end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0), tz).astimezone(UTC)
    out, t = [], start
    while t < end:
        out.append(t)
        t += QUARTER
    return out


def local_slot(ts: dt.datetime, tz: ZoneInfo = LOCAL_TZ) -> int:
    """Index 0..95 of the local quarter-hour of the day."""
    local = ts.astimezone(tz)
    return local.hour * 4 + local.minute // 15


def baseload_profile(history_kw: Mapping[dt.datetime, float], default_kw: float) -> list[float]:
    """Median house load per local quarter-hour slot from recent history (kW)."""
    by_slot: dict[int, list[float]] = {}
    for ts, kw in history_kw.items():
        by_slot.setdefault(local_slot(ts), []).append(kw)
    return [statistics.median(by_slot[s]) if by_slot.get(s) else default_kw for s in range(96)]


def surplus_flags(
    quarters: Sequence[dt.datetime],
    pv_forecast_kw: Mapping[dt.datetime, float],
    baseload: Sequence[float],
    prices_eur_mwh: Mapping[dt.datetime, float],
    *,
    pv_max_kw: float,
    threshold_kw: float,
    min_window_quarters: int,
    negative_price_windows: bool,
) -> list[int]:
    """1 where flexible load should run: forecast surplus >= threshold, or price <= 0.

    Windows shorter than ``min_window_quarters`` are dropped to avoid relay chatter.
    Missing forecast counts as no surplus (fail safe: flag 0).
    """
    raw = []
    for q in quarters:
        pv = min(pv_forecast_kw.get(q, 0.0), pv_max_kw)
        surplus = pv - baseload[local_slot(q)]
        price = prices_eur_mwh.get(q)
        cheap = negative_price_windows and price is not None and price <= 0
        raw.append(1 if surplus >= threshold_kw or cheap else 0)
    return drop_short_windows(raw, min_window_quarters)


def drop_short_windows(flags: Sequence[int], min_len: int) -> list[int]:
    out = list(flags)
    i = 0
    while i < len(out):
        if out[i] == 1:
            j = i
            while j < len(out) and out[j] == 1:
                j += 1
            if j - i < min_len:
                out[i:j] = [0] * (j - i)
            i = j
        else:
            i += 1
    return out


def event_name(day: dt.date, steering: bool) -> str:
    return f"open-rec {day.isoformat()} {'steer' if steering else 'control'}"


def build_event(
    program_id: str,
    day: dt.date,
    quarters: Sequence[dt.datetime],
    prices_eur_mwh: Mapping[dt.datetime, float],
    flags: Sequence[int],
    *,
    steering: bool,
) -> dict:
    """OpenADR 3 event body. On control days every SIMPLE value is 0."""
    if len(flags) != len(quarters):
        raise ValueError("flags and quarters must have the same length")
    intervals = []
    for i, q in enumerate(quarters):
        payloads = [{"type": "SIMPLE", "values": [flags[i] if steering else 0]}]
        price = prices_eur_mwh.get(q)
        if price is not None:
            payloads.insert(0, {"type": "PRICE", "values": [round(price / 1000, 5)]})
        intervals.append({"id": i, "payloads": payloads})
    return {
        "programID": program_id,
        "eventName": event_name(day, steering),
        "priority": None,
        "targets": [],
        "payloadDescriptors": [
            {"objectType": "EVENT_PAYLOAD_DESCRIPTOR", "payloadType": "PRICE", "units": "KWH", "currency": "EUR"},
            {"objectType": "EVENT_PAYLOAD_DESCRIPTOR", "payloadType": "SIMPLE"},
        ],
        "intervalPeriod": {"start": quarters[0].isoformat().replace("+00:00", "Z"), "duration": "PT15M"},
        "intervals": intervals,
    }


_DUR = re.compile(
    r"^P(?:(?P<y>\d+)Y)?(?:(?P<mo>\d+)M)?(?:(?P<w>\d+)W)?(?:(?P<d>\d+)D)?"
    r"(?:T(?:(?P<h>\d+)H)?(?:(?P<mi>\d+)M)?(?:(?P<s>\d+(?:\.\d+)?)S)?)?$"
)


def parse_duration(value: str) -> dt.timedelta:
    """ISO 8601 duration as used by OpenADR. Years and months must be zero."""
    m = _DUR.match(value)
    if not m:
        raise ValueError(f"unsupported duration: {value}")
    g = {k: float(v) if v else 0.0 for k, v in m.groupdict().items()}
    if g["y"] or g["mo"]:
        raise ValueError(f"year/month durations not supported: {value}")
    return dt.timedelta(weeks=g["w"], days=g["d"], hours=g["h"], minutes=g["mi"], seconds=g["s"])


def _parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def simple_value_at(event: Mapping, now: dt.datetime) -> int | None:
    """SIMPLE value of the interval covering ``now``, or None if no interval covers it."""
    default = event.get("intervalPeriod") or {}
    for idx, interval in enumerate(event.get("intervals") or []):
        period = interval.get("intervalPeriod") or {}
        start_s = period.get("start") or default.get("start")
        dur_s = period.get("duration") or default.get("duration")
        if not start_s or not dur_s:
            continue
        duration = parse_duration(dur_s)
        start = _parse_ts(start_s)
        if not interval.get("intervalPeriod"):
            start = start + duration * idx  # intervals follow each other from the event start
        if start <= now < start + duration:
            for p in interval.get("payloads") or []:
                if p.get("type") == "SIMPLE" and p.get("values"):
                    return int(p["values"][0])
            return 0
    return None


def current_flag(events: Sequence[Mapping], now: dt.datetime) -> int:
    """Flag for ``now`` across all events; most recently modified event wins. Default 0 (fail safe)."""
    ordered = sorted(events, key=lambda e: e.get("modificationDateTime") or "", reverse=True)
    for ev in ordered:
        value = simple_value_at(ev, now)
        if value is not None:
            return value
    return 0
