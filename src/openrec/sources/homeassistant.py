"""Minimal Home Assistant REST client: read sensor states, switch an entity."""

from __future__ import annotations

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
            return float(resp.json()["state"])
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
