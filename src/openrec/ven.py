"""VEN bridge: read the community's OpenADR events and set one Home Assistant flag.

The bridge never drives a device directly by default. It turns a Home Assistant
helper (input_boolean.open_rec_surplus_window) on during surplus windows and off
otherwise; Home Assistant automations decide what that means for each device,
so thermostats, safety cut-outs and manual overrides stay in Home Assistant.

Fail safe: if the VTN can't be reached for ``max_failures`` polls in a row, the
flag is turned off.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import dataclass, field

from .logic import UTC, current_flag
from .sources.homeassistant import HomeAssistant
from .vtn import VtnClient

log = logging.getLogger("open-rec.ven")


@dataclass
class Bridge:
    vtn: VtnClient
    ha: HomeAssistant
    entity: str
    program_name: str
    max_failures: int = 3
    reassert_every: dt.timedelta = dt.timedelta(minutes=15)
    _program_id: str | None = None
    _failures: int = 0
    _last: int | None = None
    _last_set_at: dt.datetime | None = field(default=None)

    def desired_flag(self, now: dt.datetime) -> int | None:
        """Flag from the VTN, or None if the VTN couldn't be read."""
        try:
            if self._program_id is None:
                self._program_id = self.vtn.find_program_id(self.program_name)
                if self._program_id is None:
                    log.warning("program %r not found on VTN yet", self.program_name)
                    return 0
            events = self.vtn.events(self._program_id)
            self._failures = 0
            return current_flag(events, now)
        except Exception as exc:
            self._failures += 1
            log.warning("VTN poll failed (%d in a row): %s", self._failures, exc)
            return None

    def tick(self, now: dt.datetime | None = None) -> int:
        """One poll. Returns the flag that is now set in Home Assistant."""
        now = now or dt.datetime.now(UTC)
        flag = self.desired_flag(now)
        if flag is None:
            flag = 0 if self._failures >= self.max_failures else (self._last or 0)
        stale = self._last_set_at is None or now - self._last_set_at >= self.reassert_every
        if flag != self._last or stale:
            self.ha.set_on(self.entity, flag == 1)
            log.info("%s -> %s", self.entity, "on" if flag else "off")
            self._last, self._last_set_at = flag, now
        return flag


def run_forever(bridge: Bridge, poll_seconds: int = 30) -> None:  # pragma: no cover - loop
    while True:
        try:
            bridge.tick()
        except Exception as exc:  # Home Assistant unreachable: keep polling
            log.error("bridge tick failed: %s", exc)
        time.sleep(poll_seconds)
