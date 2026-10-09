#
# GoogleFindMyTools - A set of tools to interact with the Google Find My API
# Copyright © 2024 Leon Böttger. All rights reserved.
#
"""Sequential relay scheduler and lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time

from .config import Config
from .database import Database
from .findhub import FindHubClient
from .osmand import OsmandSender

LOGGER = logging.getLogger(__name__)


class RelayService:
    def __init__(
        self,
        config: Config,
        database: Database,
        findhub: FindHubClient,
        sender: OsmandSender,
    ):
        self.config = config
        self.database = database
        self.findhub = findhub
        self.sender = sender
        self._last_refresh = 0.0

    async def refresh_devices(self) -> list[dict]:
        devices = await self.findhub.list_devices()
        self.database.replace_devices(devices)
        self._last_refresh = time.monotonic()
        return self.database.list_devices()

    async def selected_devices(self, *, force_refresh: bool = False) -> list[dict]:
        devices = self.database.list_devices()
        if force_refresh or not devices or (
            time.monotonic() - self._last_refresh
            >= self.config.device_refresh_interval_seconds
        ):
            devices = await self.refresh_devices()
        if self.config.device_ids is None:
            return devices
        by_id = {item["device_id"]: item for item in devices}
        missing = [device_id for device_id in self.config.device_ids if device_id not in by_id]
        if missing:
            raise RuntimeError(f"configured DEVICE_IDS not found: {', '.join(missing)}")
        return [by_id[device_id] for device_id in self.config.device_ids]

    async def run_cycle(self, *, force_refresh: bool = False) -> dict:
        started = int(time.time())
        self.database.set_health(cycle_started_at=started, last_error=None)
        errors: list[str] = []
        queried = queued = 0
        try:
            devices = await self.selected_devices(force_refresh=force_refresh)
            for device in devices:  # Deliberately sequential: one outstanding UUID request.
                device_id = device["device_id"]
                try:
                    locations = await self.findhub.locate(device_id)
                    queued += self.database.enqueue_positions(device_id, locations)
                    queried += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    LOGGER.error("Location request failed for device %s: %s", device_id, exc)
                    errors.append(f"{device_id}: {type(exc).__name__}: {exc}")
            sent, delivery_failures = await self.sender.flush()
            if delivery_failures:
                errors.append(f"{delivery_failures} outbound deliveries failed")
            status = "degraded" if errors else "ok"
            self.database.set_health(
                cycle_status=status,
                cycle_finished_at=int(time.time()),
                last_error="; ".join(errors) if errors else None,
            )
            return {
                "status": status,
                "devices_queried": queried,
                "positions_queued": queued,
                "positions_sent": sent,
                "errors": errors,
            }
        except asyncio.CancelledError:
            self.database.set_health(
                cycle_status="cancelled", cycle_finished_at=int(time.time())
            )
            raise
        except Exception as exc:
            self.database.set_health(
                cycle_status="failed",
                cycle_finished_at=int(time.time()),
                last_error=f"{type(exc).__name__}: {exc}",
            )
            raise

    async def run_daemon(self, stop_event: asyncio.Event) -> None:
        self.database.set_health(daemon_status="running", started_at=int(time.time()))
        try:
            first = True
            while not stop_event.is_set():
                try:
                    await self.run_cycle(force_refresh=first)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.exception("Relay cycle failed; next cycle will retry")
                first = False
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self.config.poll_interval_seconds
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            self.database.set_health(daemon_status="stopped")
