"""Single-flight read-only polling for observed PS19001 legacy feedback."""

from __future__ import annotations

import asyncio
import logging
import time

IDLE_INTERVAL = 10.0
MOVING_INTERVAL = 2.0
RESPONSE_TIMEOUT = 8.0
FAST_WINDOW = 90.0
_LOGGER = logging.getLogger(__name__)


class StatusPoller:
    """Entry-owned poller; cannot publish movement or configuration commands."""

    def __init__(self, client, *, clock=time.monotonic, sleep=asyncio.sleep):
        self.client = client
        self.clock, self.sleep = clock, sleep
        self.waiting = False
        self.requests = self.responses = self.failures = 0
        self.active_since = None
        self.last_state = None

    def snapshot(self):
        return {"waiting": self.waiting, "requests": self.requests,
                "responses": self.responses, "consecutive_failures": self.failures}

    async def sample(self, executor):
        """One request only, awaiting its reply before any further publish."""
        before = self.client.system_status_generation
        self.waiting = True
        try:
            if not await executor(self.client.request_fresh_system_status):
                self.failures += 1
                return
            self.requests += 1
            deadline = self.clock() + RESPONSE_TIMEOUT
            while self.client.system_status_generation == before:
                if not self.client.is_connected or self.clock() >= deadline:
                    self.failures += 1
                    return
                await self.sleep(0.1)
            self.responses += 1
            self.failures = 0
        finally:
            self.waiting = False

    def interval(self):
        if self.failures:
            return min(60.0, IDLE_INTERVAL * 2 ** min(self.failures, 3))
        state = self.client.state.gate_state
        if state != self.last_state and state in ("opening", "closing"):
            self.active_since = self.clock()
        self.last_state = state
        if self.client.physical_gate_closed is False:
            if self.active_since is None:
                self.active_since = self.clock()
            if self.clock() - self.active_since < FAST_WINDOW:
                return MOVING_INTERVAL
        else:
            self.active_since = None
        return IDLE_INTERVAL

    async def run(self, executor):
        while True:
            ready = (self.client.uses_access_mode_feedback and self.client.is_connected
                     and self.client.state.uart_version == 1)
            if not ready:
                await self.sleep(2.0)
                continue
            started = self.clock()
            try:
                await self.sample(executor)
            except Exception as err:
                self.failures += 1
                _LOGGER.warning("Powertech status poll failed (%s)", type(err).__name__)
            # Idle snapshots need not be written every second; nevertheless a
            # timeout must make stale feedback unavailable to the entity layer.
            self.client._notify()
            await self.sleep(max(0.1, self.interval() - (self.clock() - started)))
