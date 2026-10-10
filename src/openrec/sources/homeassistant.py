"""Minimal Home Assistant REST client: read sensor states, switch an entity."""

from __future__ import annotations

import math

import httpx


class HomeAssistant:
    def __init__(self, url: str, token: str, client: httpx.Client | None = None):
        self.url = url.rstrip("/")
        self.client = client or httpx.Client(timeout=10)
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def state(self, entity_id: str) -> float | None:
        """Numeric state of a sensor, or None if unavailable/unknown."""
        resp = self.client.get(f"{self.url}/api/states/{entity_id}", headers=self.headers)
        resp.raise_for_status()
        try:
            value = float(resp.json()["state"])
            return value if math.isfinite(value) and value >= 0 else None
        except (KeyError, TypeError, ValueError):
            return None

    def set_on(self, entity_id: str, on: bool) -> None:
        """turn_on / turn_off on the entity's own domain (input_boolean, switch, ...)."""
        domain = entity_id.split(".", 1)[0]
        service = "turn_on" if on else "turn_off"
        resp = self.client.post(
            f"{self.url}/api/services/{domain}/{service}", headers=self.headers, json={"entity_id": entity_id}
        )
        resp.raise_for_status()

    def set_lease(self, entity_id: str, active: bool) -> None:
        """HA expires this permission independently if the bridge stops polling."""
        service = "start" if active else "cancel"
        body = {"entity_id": entity_id}
        if active:
            body["duration"] = "00:02:00"
        resp = self.client.post(
            f"{self.url}/api/services/timer/{service}", headers=self.headers, json=body
        )
        resp.raise_for_status()
