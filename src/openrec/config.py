"""Settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _float(name: str, default: float) -> float:
    return float(_env(name, str(default)))


@dataclass(frozen=True)
class Settings:
    # Storage for open-rec's own data (prices, forecasts, readings, test plan)
    database_url: str
    # VTN (openleadr-rs). The service acts as the business logic (BL) client.
    vtn_url: str
    bl_client_id: str
    bl_client_secret: str
    program_name: str
    # VEN bridge credentials (one per home)
    ven_client_id: str
    ven_client_secret: str
    ven_name: str
    # PV site
    site_lat: float
    site_lon: float
    pv_kwp: float
    pv_tilt: float
    pv_azimuth: float  # Open-Meteo convention: 0 = south, -90 = east, 90 = west
    pv_max_kw: float  # inverter output cap
    pv_performance_ratio: float
    # Event logic
    surplus_threshold_kw: float
    baseload_kw_default: float
    min_window_quarters: int
    negative_price_windows: bool
    publish_time_local: dt.time
    # Home Assistant
    ha_url: str | None
    ha_token: str | None
    ha_pv_energy_entity: str | None
    ha_house_energy_entity: str | None
    ha_steered_energy_entity: str | None  # optional meter on the steered load (e.g. water heater)
    ha_window_entity: str
    # Test plan (alternating steering-on / steering-off days)
    test_plan_start: dt.date | None
    test_plan_seed: str
    ha_lease_entity: str = "timer.open_rec_bridge_lease"

    @classmethod
    def from_env(cls) -> "Settings":
        start = _env("TEST_PLAN_START")
        hh, mm = (_env("PUBLISH_TIME_LOCAL", "14:30") or "14:30").split(":")
        return cls(
            database_url=_env("OPENREC_DATABASE_URL", "postgresql://openadr:openadr@localhost:5432/openrec"),
            vtn_url=(_env("VTN_URL", "http://localhost:3000") or "").rstrip("/"),
            bl_client_id=_env("VTN_BL_CLIENT_ID", "open-rec-bl"),
            bl_client_secret=_env("VTN_BL_CLIENT_SECRET", ""),
            program_name=_env("VTN_PROGRAM_NAME", "open-rec-surplus"),
            ven_client_id=_env("VEN_CLIENT_ID", "open-rec-ven-1"),
            ven_client_secret=_env("VEN_CLIENT_SECRET", ""),
            ven_name=_env("VEN_NAME", "home-1"),
            site_lat=_float("SITE_LAT", 39.9),
            site_lon=_float("SITE_LON", -8.6),
            pv_kwp=_float("PV_KWP", 2.7),
            pv_tilt=_float("PV_TILT", 30),
            pv_azimuth=_float("PV_AZIMUTH", 0),
            pv_max_kw=_float("PV_MAX_KW", 3.0),
            pv_performance_ratio=_float("PV_PERFORMANCE_RATIO", 0.85),
            surplus_threshold_kw=_float("SURPLUS_THRESHOLD_KW", 1.0),
            baseload_kw_default=_float("BASELOAD_KW_DEFAULT", 0.3),
            min_window_quarters=int(_env("MIN_WINDOW_QUARTERS", "2")),
            negative_price_windows=(_env("NEGATIVE_PRICE_WINDOWS", "false") or "false").lower() == "true",
            publish_time_local=dt.time(int(hh), int(mm)),
            ha_url=(_env("HA_URL") or "").rstrip("/") or None,
            ha_token=_env("HA_TOKEN"),
            ha_pv_energy_entity=_env("HA_PV_ENERGY_ENTITY"),
            ha_house_energy_entity=_env("HA_HOUSE_ENERGY_ENTITY"),
            ha_steered_energy_entity=_env("HA_STEERED_ENERGY_ENTITY"),
            ha_window_entity=_env("HA_WINDOW_ENTITY", "input_boolean.open_rec_surplus_window"),
            test_plan_start=dt.date.fromisoformat(start) if start else None,
            test_plan_seed=_env("TEST_PLAN_SEED", "open-rec"),
            ha_lease_entity=_env("HA_LEASE_ENTITY", "timer.open_rec_bridge_lease"),
        )
