"""Alternating steering-on / steering-off test days.

Paired design: days are grouped in consecutive pairs from the plan start, and
one day of each pair is chosen at random (deterministically, from the seed) to
be the steering day. Adjacent days have similar weather and season, so the
on-minus-off difference within each pair cancels most of the seasonal trend.
"""

from __future__ import annotations

import datetime as dt
import hashlib


def is_steering_day(day: dt.date, start: dt.date | None, seed: str) -> bool:
    """True if devices should be steered on ``day``. Before the plan starts, always steer."""
    if start is None or day < start:
        return True
    offset = (day - start).days
    pair, position = divmod(offset, 2)
    digest = hashlib.sha256(f"{seed}:{start.isoformat()}:{pair}".encode()).digest()
    steering_position = digest[0] & 1
    return position == steering_position


def pair_of(day: dt.date, start: dt.date) -> int:
    return (day - start).days // 2
