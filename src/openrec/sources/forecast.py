"""PV forecast from Open-Meteo's free API (no key needed).

Uses 15-minute global tilted irradiance (GTI) for the panel's tilt and azimuth:
  kW = GTI / 1000 * kWp * performance ratio, capped at the inverter limit.
Open-Meteo radiation values are means over the *preceding* period, so a value
stamped t covers [t - 15 min, t).
"""

from __future__ import annotations

import datetime as dt
import math

import httpx

from ..logic import QUARTER, UTC

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def gti_to_kw(gti_w_m2: float | None, kwp: float, performance_ratio: float, max_kw: float) -> float:
    if gti_w_m2 is None or gti_w_m2 <= 0:
        return 0.0
    return min(gti_w_m2 / 1000 * kwp * performance_ratio, max_kw)


def parse_open_meteo(payload: dict, kwp: float, performance_ratio: float, max_kw: float) -> dict[dt.datetime, float]:
    block = payload["minutely_15"]
    out = {}
    for stamp, gti in zip(block["time"], block["global_tilted_irradiance"]):
        if gti is None or not math.isfinite(gti):
            continue  # Unknown radiation must remain missing, not become valid zero.
        end = dt.datetime.fromisoformat(stamp).replace(tzinfo=UTC)
        out[end - QUARTER] = gti_to_kw(gti, kwp, performance_ratio, max_kw)
    return out


def fetch_pv_forecast(
    lat: float,
    lon: float,
    tilt: float,
    azimuth: float,
    kwp: float,
    performance_ratio: float,
    max_kw: float,
    days: int = 2,
    client: httpx.Client | None = None,
) -> dict[dt.datetime, float]:
    """Forecast PV output in kW, keyed by UTC quarter start."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "minutely_15": "global_tilted_irradiance",
        "tilt": tilt,
        "azimuth": azimuth,
        "timezone": "UTC",
        "forecast_days": days,
        "past_days": 1,  # Madrid's current market day starts on the preceding UTC date.
    }
    own = client is None
    client = client or httpx.Client(timeout=20)
    try:
        resp = client.get(OPEN_METEO_URL, params=params)
        resp.raise_for_status()
        return parse_open_meteo(resp.json(), kwp, performance_ratio, max_kw)
    finally:
        if own:
            client.close()
