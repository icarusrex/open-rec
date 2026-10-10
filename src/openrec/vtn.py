"""Small OpenADR 3 client for an openleadr-rs VTN (internal OAuth, client credentials)."""

from __future__ import annotations

import time

import httpx

PAGE = 50  # openleadr-rs maximum page size


class VtnClient:
    def __init__(self, base_url: str, client_id: str, client_secret: str, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = client or httpx.Client(timeout=15)
        self._token: str | None = None
        self._expires_at = 0.0

    # --- auth ---------------------------------------------------------------
    def token(self) -> str:
        if self._token and time.monotonic() < self._expires_at - 30:
            return self._token
        resp = self.http.post(
            f"{self.base_url}/auth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._expires_at = time.monotonic() + float(body.get("expires_in", 300))
        return self._token

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.token()}"}
        resp = self.http.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{method} {path} -> {resp.status_code}: {resp.text[:500]}", request=resp.request, response=resp
            )
        return resp

    def _list(self, path: str, params: dict | None = None) -> list[dict]:
        """All items of a collection. openleadr-rs returns at most 50 per request."""
        items: list[dict] = []
        while True:
            page = self._request("GET", path, params={**(params or {}), "skip": len(items), "limit": PAGE}).json()
            items.extend(page)
            if len(page) < PAGE:
                return items

    # --- programs -------------------------------------------------------------
    def programs(self) -> list[dict]:
        return self._list("/programs")

    def ensure_program(self, name: str) -> str:
        """ID of the program with this name, creating it if needed."""
        for p in self.programs():
            if p.get("programName") == name:
                return p["id"]
        body = {
            "programName": name,
            "programDescriptions": [{"URL": "https://github.com/icarusrex/open-rec"}],
            "payloadDescriptors": [
                {"objectType": "EVENT_PAYLOAD_DESCRIPTOR", "payloadType": "PRICE", "units": "KWH", "currency": "EUR"},
                {"objectType": "EVENT_PAYLOAD_DESCRIPTOR", "payloadType": "SIMPLE"},
            ],
        }
        return self._request("POST", "/programs", json=body).json()["id"]

    def find_program_id(self, name: str) -> str | None:
        for p in self.programs():
            if p.get("programName") == name:
                return p["id"]
        return None

    # --- events ---------------------------------------------------------------
    def events(self, program_id: str | None = None) -> list[dict]:
        return self._list("/events", {"programID": program_id} if program_id else None)

    def prune_events(self, program_id: str, keep_from: str) -> int:
        """Delete this program's open-rec events for days before ``keep_from`` (YYYY-MM-DD).

        Keeps the VTN's event list short, so VENs poll a page or two, not a year of history.
        """
        deleted = 0
        for e in self.events(program_id):
            name = e.get("eventName") or ""
            if name.startswith("open-rec ") and name[9:19] < keep_from:
                self._request("DELETE", f"/events/{e['id']}")
                deleted += 1
        return deleted

    def upsert_event(self, body: dict, day_prefix: str) -> dict:
        """Create the event, or replace any existing event of the same program and day.

        ``day_prefix`` is the start of the event name that identifies the day,
        e.g. ``"open-rec 2026-10-11"``; both steer and control names match it.
        """
        existing = [
            e
            for e in self.events(body["programID"])
            if (e.get("eventName") or "").startswith(day_prefix)
        ]
        if existing:
            keep, *extra = existing
            for e in extra:
                self._request("DELETE", f"/events/{e['id']}")
            return self._request("PUT", f"/events/{keep['id']}", json=body).json()
        return self._request("POST", "/events", json=body).json()

    # --- VENs -----------------------------------------------------------------
    def ensure_ven(self, ven_name: str) -> str:
        """Register this VEN client (as the VEN itself) if it isn't yet; returns its ID."""
        for v in self._list("/vens"):
            if v.get("venName") == ven_name:
                return v["id"]
        body = {"objectType": "VEN_VEN_REQUEST", "venName": ven_name}
        return self._request("POST", "/vens", json=body).json()["id"]
