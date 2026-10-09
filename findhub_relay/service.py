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
        cycle_started = time.monotonic()
        started = int(time.time())
        errors: list[str] = []
        selected = queried = queued = sent = delivery_failures = 0
        status = "failed"
        LOGGER.info("Relay cycle started")
        self.database.set_health(cycle_started_at=started, last_error=None)
        try:
            devices = await self.selected_devices(force_refresh=force_refresh)
            selected = len(devices)
            for device in devices:  # Deliberately sequential: one outstanding UUID request.
                device_id = device["device_id"]
                try:
                    locations = await self.findhub.locate(device_id)
                    LOGGER.info(
                        "Find Hub query succeeded device_id=%s reports=%d",
                        device_id,
                        len(locations),
                    )
                    queued += self.database.enqueue_positions(device_id, locations)
                    queried += 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    error_type = type(exc).__name__
                    LOGGER.error(
                        "Find Hub query failed device_id=%s error_type=%s",
                        device_id,
                        error_type,
                    )
                    errors.append(f"{device_id}: {error_type}")
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
            status = "cancelled"
            self.database.set_health(
                cycle_status=status, cycle_finished_at=int(time.time())
            )
            raise
        except Exception as exc:
            error_type = type(exc).__name__
            self.database.set_health(
                cycle_status="failed",
                cycle_finished_at=int(time.time()),
                last_error=error_type,
            )
            LOGGER.error("Relay cycle failed error_type=%s", error_type)
            raise
        finally:
            pending_positions = -1
            try:
                pending_positions = self.database.pending_position_count()
            except Exception as exc:
                LOGGER.warning(
                    "Relay cycle pending count failed error_type=%s",
                    type(exc).__name__,
                )
            LOGGER.info(
                "Relay cycle completed status=%s devices_selected=%d "
                "devices_queried=%d positions_queued=%d positions_sent=%d "
                "delivery_failures=%d pending_positions=%d duration_seconds=%.3f",
                status,
                selected,
                queried,
                queued,
                sent,
                delivery_failures,
                pending_positions,
                time.monotonic() - cycle_started,
            )

    async def run_daemon(self, stop_event: asyncio.Event) -> None:
        self.database.set_health(daemon_status="running", started_at=int(time.time()))
        if self.config.device_ids is None:
            LOGGER.info(
                "Relay daemon started poll_interval_seconds=%d device_filter=all",
                self.config.poll_interval_seconds,
            )
        else:
            LOGGER.info(
                "Relay daemon started poll_interval_seconds=%d device_filter_count=%d",
                self.config.poll_interval_seconds,
                len(self.config.device_ids),
            )
        try:
            first = True
            while not stop_event.is_set():
                try:
                    await self.run_cycle(force_refresh=first)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # run_cycle records and logs the safe error type before retrying.
                    pass
                first = False
                if stop_event.is_set():
                    break
                LOGGER.info(
                    "Relay daemon waiting next_cycle_seconds=%d",
                    self.config.poll_interval_seconds,
                )
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self.config.poll_interval_seconds
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            self.database.set_health(daemon_status="stopped")
            LOGGER.info("Relay daemon stopped gracefully")
