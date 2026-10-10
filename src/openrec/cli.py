"""Command line: open-rec <command>."""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

from . import db
from .config import Settings
from .logic import LOCAL_TZ, UTC


def _date(value: str) -> dt.date:
    return dt.date.fromisoformat(value)


def cmd_init_db(settings: Settings, _args) -> int:
    db.init_schema(db.connect(settings.database_url))
    print("open-rec schema ready")
    return 0


def cmd_bootstrap(settings: Settings, args) -> int:
    from .bootstrap import bootstrap_sql, new_secret

    bl_secret = settings.bl_client_secret or new_secret()
    ven_secret = settings.ven_client_secret or new_secret()
    sql = bootstrap_sql(settings.bl_client_id, bl_secret, settings.ven_client_id, ven_secret)
    if args.apply:
        if not args.vtn_database_url:
            print("--apply needs --vtn-database-url", file=sys.stderr)
            return 2
        with db.connect(args.vtn_database_url) as conn:
            conn.execute(sql)
        print("VTN clients created or updated.")
    else:
        print(sql)
    if not settings.bl_client_secret or not settings.ven_client_secret:
        print("\n# Generated secrets - put these in .env:", file=sys.stderr)
        if not settings.bl_client_secret:
            print(f"VTN_BL_CLIENT_SECRET={bl_secret}", file=sys.stderr)
        if not settings.ven_client_secret:
            print(f"VEN_CLIENT_SECRET={ven_secret}", file=sys.stderr)
    return 0


def cmd_publish(settings: Settings, args) -> int:
    from .service import publish_day
    from .vtn import VtnClient

    conn = db.connect(settings.database_url)
    db.init_schema(conn)
    vtn = VtnClient(settings.vtn_url, settings.bl_client_id, settings.bl_client_secret)
    day = args.day or (dt.datetime.now(LOCAL_TZ).date() + dt.timedelta(days=1))
    print(publish_day(settings, conn, vtn, day))
    return 0


def cmd_collect(settings: Settings, _args) -> int:
    from .service import collect_readings
    from .sources.homeassistant import HomeAssistant

    if not (settings.ha_url and settings.ha_token):
        print("HA_URL and HA_TOKEN are required", file=sys.stderr)
        return 2
    conn = db.connect(settings.database_url)
    db.init_schema(conn)
    print(f"stored {collect_readings(settings, conn, HomeAssistant(settings.ha_url, settings.ha_token))} readings")
    return 0


def cmd_report(settings: Settings, args) -> int:
    from .report import compare, daily_metrics, format_summary, interval_energy

    if not settings.test_plan_start:
        print("TEST_PLAN_START is not set", file=sys.stderr)
        return 2
    if not (settings.ha_pv_energy_entity and settings.ha_house_energy_entity):
        print("HA_PV_ENERGY_ENTITY and HA_HOUSE_ENERGY_ENTITY are required", file=sys.stderr)
        return 2
    conn = db.connect(settings.database_url)
    start = dt.datetime.combine(settings.test_plan_start, dt.time(0), LOCAL_TZ).astimezone(UTC)
    end = dt.datetime.now(UTC)
    pv = interval_energy(db.load_readings(conn, settings.ha_pv_energy_entity, start, end))
    house = interval_energy(db.load_readings(conn, settings.ha_house_energy_entity, start, end))
    days = daily_metrics(pv, house)
    print(format_summary(compare(days, settings.test_plan_start, settings.test_plan_seed)))
    return 0


def cmd_plan(settings: Settings, args) -> int:
    from .testplan import is_steering_day

    start = settings.test_plan_start
    first = args.start or start or dt.date.today()
    for i in range(args.days):
        day = first + dt.timedelta(days=i)
        print(day.isoformat(), "steer" if is_steering_day(day, start, settings.test_plan_seed) else "control")
    return 0


def cmd_run(settings: Settings, _args) -> int:
    from .service import run_forever

    run_forever(settings)
    return 0


def cmd_ven(settings: Settings, _args) -> int:
    from .sources.homeassistant import HomeAssistant
    from .ven import Bridge, run_forever
    from .vtn import VtnClient

    if not (settings.ha_url and settings.ha_token):
        print("HA_URL and HA_TOKEN are required", file=sys.stderr)
        return 2
    vtn = VtnClient(settings.vtn_url, settings.ven_client_id, settings.ven_client_secret)
    vtn.ensure_ven(settings.ven_name)
    bridge = Bridge(vtn, HomeAssistant(settings.ha_url, settings.ha_token), settings.ha_window_entity, settings.program_name)
    run_forever(bridge)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="open-rec", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="create open-rec's tables")
    b = sub.add_parser("bootstrap", help="create the VTN clients for the service and the VEN bridge")
    b.add_argument("--apply", action="store_true", help="write to the VTN database instead of printing SQL")
    b.add_argument("--vtn-database-url")
    p = sub.add_parser("publish", help="build and publish one day's event (default: tomorrow)")
    p.add_argument("--day", type=_date)
    sub.add_parser("collect", help="store one snapshot of the HA energy counters")
    sub.add_parser("report", help="steering vs control self-consumption report")
    pl = sub.add_parser("plan", help="show the steer/control test plan")
    pl.add_argument("--start", type=_date)
    pl.add_argument("--days", type=int, default=14)
    sub.add_parser("run", help="run the service (collect every 15 min, publish daily)")
    sub.add_parser("ven", help="run the VEN bridge for this home")
    args = parser.parse_args(argv)
    handlers = {
        "init-db": cmd_init_db,
        "bootstrap": cmd_bootstrap,
        "publish": cmd_publish,
        "collect": cmd_collect,
        "report": cmd_report,
        "plan": cmd_plan,
        "run": cmd_run,
        "ven": cmd_ven,
    }
    return handlers[args.command](Settings.from_env(), args)


if __name__ == "__main__":
    sys.exit(main())
