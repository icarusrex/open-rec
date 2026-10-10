"""open-rec's own storage (separate database from the VTN's)."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Iterable, Mapping
from contextlib import contextmanager

import psycopg

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ts TIMESTAMPTZ PRIMARY KEY,
    eur_mwh DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS pv_forecast (
    ts TIMESTAMPTZ PRIMARY KEY,
    kw DOUBLE PRECISION NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS readings (
    ts TIMESTAMPTZ NOT NULL,
    entity TEXT NOT NULL,
    kwh_total DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (ts, entity)
);
CREATE TABLE IF NOT EXISTS published_events (
    day DATE PRIMARY KEY,
    event_id TEXT NOT NULL,
    steering BOOLEAN NOT NULL,
    window_quarters INTEGER NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=True)


@contextmanager
def publication_lock(conn: psycopg.Connection, program_name: str):
    """Serialize cooperating publishers using the same open-rec database.

    Program-level locking also protects duplicate cleanup and pruning against
    another day's publication. PostgreSQL releases the lock on rollback/death.
    """
    key = int.from_bytes(hashlib.sha256(program_name.encode()).digest()[:8], 'big', signed=True)
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (key,))
        yield


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA)


def save_prices(conn: psycopg.Connection, prices: Mapping[dt.datetime, float]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO prices (ts, eur_mwh) VALUES (%s, %s) ON CONFLICT (ts) DO UPDATE SET eur_mwh = EXCLUDED.eur_mwh",
            list(prices.items()),
        )


def load_prices(conn: psycopg.Connection, start: dt.datetime, end: dt.datetime) -> dict[dt.datetime, float]:
    rows = conn.execute("SELECT ts, eur_mwh FROM prices WHERE ts >= %s AND ts < %s", (start, end)).fetchall()
    return {ts: v for ts, v in rows}


def save_forecast(conn: psycopg.Connection, forecast: Mapping[dt.datetime, float]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO pv_forecast (ts, kw) VALUES (%s, %s) "
            "ON CONFLICT (ts) DO UPDATE SET kw = EXCLUDED.kw, fetched_at = now()",
            list(forecast.items()),
        )


def load_forecast(conn: psycopg.Connection, start: dt.datetime, end: dt.datetime) -> dict[dt.datetime, float]:
    rows = conn.execute("SELECT ts, kw FROM pv_forecast WHERE ts >= %s AND ts < %s", (start, end)).fetchall()
    return {ts: v for ts, v in rows}


def save_reading(conn: psycopg.Connection, ts: dt.datetime, entity: str, kwh_total: float) -> None:
    conn.execute(
        "INSERT INTO readings (ts, entity, kwh_total) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (ts, entity, kwh_total),
    )


def load_readings(conn: psycopg.Connection, entity: str, start: dt.datetime, end: dt.datetime) -> list[tuple[dt.datetime, float]]:
    return conn.execute(
        "SELECT ts, kwh_total FROM readings WHERE entity = %s AND ts >= %s AND ts < %s ORDER BY ts",
        (entity, start, end),
    ).fetchall()


def mark_published(conn: psycopg.Connection, day: dt.date, event_id: str, steering: bool, window_quarters: int) -> None:
    conn.execute(
        "INSERT INTO published_events (day, event_id, steering, window_quarters) VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (day) DO UPDATE SET event_id = EXCLUDED.event_id, steering = EXCLUDED.steering, "
        "window_quarters = EXCLUDED.window_quarters, published_at = now()",
        (day, event_id, steering, window_quarters),
    )


def is_published(conn: psycopg.Connection, day: dt.date) -> bool:
    return conn.execute("SELECT 1 FROM published_events WHERE day = %s", (day,)).fetchone() is not None


def clear_published(conn: psycopg.Connection, day: dt.date) -> None:
    conn.execute('DELETE FROM published_events WHERE day = %s', (day,))


def published_days(conn: psycopg.Connection) -> Iterable[tuple]:
    return conn.execute("SELECT day, steering, window_quarters, event_id FROM published_events ORDER BY day").fetchall()
