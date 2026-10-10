"""The open-rec service: collect readings, publish each day's event to the VTN."""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Callable

from . import db
from .config import Settings
from .logic import (
    LOCAL_TZ,
    UTC,
    baseload_profile,
    build_event,
    quarter_starts,
    surplus_flags,
)
from .report import interval_energy
from .sources.forecast import fetch_pv_forecast
from .sources.homeassistant import HomeAssistant
from .sources.omie import fetch_pt_prices
from .testplan import is_steering_day
from .vtn import VtnClient

log = logging.getLogger("open-rec")

PriceFetcher = Callable[[dt.date], dict]
ForecastFetcher = Callable[[Settings], dict]


def default_forecast(settings: Settings) -> dict:
    return fetch_pv_forecast(
        settings.site_lat,
        settings.site_lon,
        settings.pv_tilt,
        settings.pv_azimuth,
        settings.pv_kwp,
        settings.pv_performance_ratio,
        settings.pv_max_kw,
    )


def baseload_from_history(conn, settings: Settings, now: dt.datetime) -> list[float]:
    """Median house load per quarter-hour over the last 14 days, from HA readings.

    If the steered load has its own energy meter, its consumption is subtracted,
    so past steering doesn't inflate the baseload and shrink future windows.
    """
    if not settings.ha_house_energy_entity:
        return [settings.baseload_kw_default] * 96
    since = now - dt.timedelta(days=14)
    house = interval_energy(db.load_readings(conn, settings.ha_house_energy_entity, since, now))
    steered = {}
    if settings.ha_steered_energy_entity:
        steered = interval_energy(db.load_readings(conn, settings.ha_steered_energy_entity, since, now))
    kw = {q: max(kwh - steered.get(q, 0.0), 0.0) * 4 for q, kwh in house.items()}
    return baseload_profile(kw, settings.baseload_kw_default)


def publish_day(
    settings: Settings,
    conn,
    vtn: VtnClient,
    day: dt.date,
    *,
    prices_fetcher: PriceFetcher = fetch_pt_prices,
    forecast_fetcher: ForecastFetcher = default_forecast,
    now: dt.datetime | None = None,
) -> dict:
    """Build and publish the event for ``day``. Missing data degrades to fewer windows, never more."""
    now = now or dt.datetime.now(UTC)
    quarters = quarter_starts(day)
    start, end = quarters[0], quarters[-1] + dt.timedelta(minutes=15)

    try:
        db.save_prices(conn, prices_fetcher(day))
    except Exception as exc:  # network, OMIE not yet published, parse error
        log.warning("OMIE prices for %s unavailable: %s", day, exc)
    try:
        db.save_forecast(conn, forecast_fetcher(settings))
    except Exception as exc:
        log.warning("PV forecast unavailable: %s", exc)

    prices = db.load_prices(conn, start, end)
    forecast = db.load_forecast(conn, start, end)
    baseload = baseload_from_history(conn, settings, now)
    flags = surplus_flags(
        quarters,
        forecast,
        baseload,
        prices,
        pv_max_kw=settings.pv_max_kw,
        threshold_kw=settings.surplus_threshold_kw,
        min_window_quarters=settings.min_window_quarters,
        negative_price_windows=settings.negative_price_windows,
    )
    steering = is_steering_day(day, settings.test_plan_start, settings.test_plan_seed)
    program_id = vtn.ensure_program(settings.program_name)
    body = build_event(program_id, day, quarters, prices, flags, steering=steering)
    event = vtn.upsert_event(body, f"open-rec {day.isoformat()}")
    db.mark_published(conn, day, event["id"], steering, sum(flags))
    summary = {
        "day": day.isoformat(),
        "event_id": event["id"],
        "steering": steering,
        "window_quarters": sum(flags),
        "prices": len(prices),
        "forecast_quarters": len(forecast),
    }
    log.info("published %s", summary)
    return summary


def collect_readings(settings: Settings, conn, ha: HomeAssistant, now: dt.datetime | None = None) -> int:
    """Snapshot the cumulative kWh counters from Home Assistant. Returns how many were stored."""
    now = now or dt.datetime.now(UTC)
    stored = 0
    for entity in (settings.ha_pv_energy_entity, settings.ha_house_energy_entity, settings.ha_steered_energy_entity):
        if not entity:
            continue
        value = ha.state(entity)
        if value is not None:
            db.save_reading(conn, now, entity, value)
            stored += 1
    return stored


def run_forever(settings: Settings, tick_seconds: int = 30) -> None:  # pragma: no cover - loop
    conn = db.connect(settings.database_url)
    db.init_schema(conn)
    vtn = VtnClient(settings.vtn_url, settings.bl_client_id, settings.bl_client_secret)
    ha = HomeAssistant(settings.ha_url, settings.ha_token) if settings.ha_url and settings.ha_token else None
    last_quarter = None
    retry_after = 0.0
    while True:
        now = dt.datetime.now(UTC)
        quarter = now.replace(minute=now.minute - now.minute % 15, second=0, microsecond=0)
        if ha and quarter != last_quarter:
            try:
                collect_readings(settings, conn, ha, now)
            except Exception as exc:
                log.warning("reading collection failed: %s", exc)
            last_quarter = quarter

        local = now.astimezone(LOCAL_TZ)
        today, tomorrow = local.date(), local.date() + dt.timedelta(days=1)
        due = [d for d in (today,) if not db.is_published(conn, d)]
        if local.time() >= settings.publish_time_local and not db.is_published(conn, tomorrow):
            due.append(tomorrow)
        if due and time.monotonic() >= retry_after:
            for day in due:
                try:
                    publish_day(settings, conn, vtn, day, now=now)
                except Exception as exc:
                    log.error("publishing %s failed, retrying in 15 min: %s", day, exc)
                    retry_after = time.monotonic() + 900
                    break
        time.sleep(tick_seconds)
