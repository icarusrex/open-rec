"""Create the VTN credentials open-rec needs (internal OAuth of openleadr-rs).

openleadr-rs stores clients in its own database with argon2 secret hashes.
The very first business-logic client can't be created through the API (that
needs a client that already has the write_users scope), so we insert it with SQL.
"""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher

BL_SCOPES = [
    "read_all",
    "write_programs",
    "write_events",
    "write_vens_bl",
    "write_reports_bl",
    "write_subscriptions_bl",
    "write_users",
]
VEN_SCOPES = ["read_targets", "read_ven_objects", "write_reports_ven", "write_subscriptions_ven", "write_vens_ven"]


def new_secret() -> str:
    return secrets.token_urlsafe(24)


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def user_sql(user_id: str, client_id: str, secret: str, scopes: list[str], description: str) -> str:
    hashed = PasswordHasher().hash(secret)
    scope_array = "'{" + ",".join(f'"{s}"' for s in scopes) + "}'"
    return (
        f'INSERT INTO "user" (id, reference, description, scopes, created, modified) '
        f"VALUES ({_sql_str(user_id)}, {_sql_str(user_id)}, {_sql_str(description)}, {scope_array}, now(), now()) "
        f"ON CONFLICT (id) DO NOTHING;\n"
        f"INSERT INTO user_credentials (user_id, client_id, client_secret) "
        f"VALUES ({_sql_str(user_id)}, {_sql_str(client_id)}, {_sql_str(hashed)}) "
        f"ON CONFLICT (client_id) DO UPDATE SET client_secret = EXCLUDED.client_secret;\n"
    )


def bootstrap_sql(bl_client_id: str, bl_secret: str, ven_client_id: str, ven_secret: str) -> str:
    return user_sql(bl_client_id, bl_client_id, bl_secret, BL_SCOPES, "open-rec service (business logic)") + user_sql(
        ven_client_id, ven_client_id, ven_secret, VEN_SCOPES, "open-rec VEN bridge"
    )
