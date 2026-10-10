"""OMIE day-ahead prices for Portugal, via pyomie.

OMIE publishes D+1 results around 13:00 CET. Since October 2025 the day-ahead
market clears in 15-minute periods; period 1 starts at 00:00 CET/CEST.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Sequence

import aiohttp
from pyomie.main import spot_price

from ..logic import quarter_starts


def map_quarters(day: dt.date, values: Sequence[float]) -> dict[dt.datetime, float]:
    """Attach OMIE quarter values (EUR/MWh) to their UTC interval starts."""
    quarters = quarter_starts(day)
    if len(values) != len(quarters):
        raise ValueError(f"OMIE returned {len(values)} values for {day}, expected {len(quarters)}")
    return dict(zip(quarters, values))


async def _fetch(day: dt.date) -> list[float]:
    async with aiohttp.ClientSession() as session:
        result = await spot_price(session, day)
    return list(result.contents.pt_spot_price)


def fetch_pt_prices(day: dt.date) -> dict[dt.datetime, float]:
    """Portuguese day-ahead prices for ``day`` in EUR/MWh, keyed by UTC quarter start."""
    return map_quarters(day, asyncio.run(_fetch(day)))
