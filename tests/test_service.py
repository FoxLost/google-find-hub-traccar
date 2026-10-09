# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import asyncio
import tempfile
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from findhub_relay.config import Config
from findhub_relay.database import Database
from findhub_relay.service import RelayService


class FakeFindHub:
    def __init__(self):
        self.calls = []

    async def list_devices(self):
        return [("Broken", "bad"), ("Working", "good")]

    async def locate(self, device_id):
        self.calls.append(device_id)
        if device_id == "bad":
            raise TimeoutError("SECRET_TOKEN response=(12.345,67.89)")
        return [{"time": 123, "latitude": 1, "longitude": 2}]


class FakeSender:
    async def flush(self):
        return (1, 0)

class FakeFailingSender:
    async def flush(self):
        return (0, 2)


class SchedulerBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_failure_does_not_prevent_next_device(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "relay.db")
            database.initialize()
            config = Config(
                traccar_url="http://example",
                poll_interval_seconds=900,
                location_timeout_seconds=30,
                device_refresh_interval_seconds=3600,
                device_ids=None,
                data_directory=Path(directory),
                credentials_file=Path(directory) / "credentials.json",
                log_level="INFO",
            )
            findhub = FakeFindHub()
            service = RelayService(config, database, findhub, FakeFailingSender())
            with self.assertLogs("findhub_relay.service", level="INFO") as captured:
                result = await service.run_cycle(force_refresh=True)
            self.assertEqual(findhub.calls, ["bad", "good"])
            self.assertEqual(result["status"], "degraded")
            self.assertEqual(result["devices_queried"], 1)
            self.assertEqual(
                result["errors"],
                ["bad: TimeoutError", "2 outbound deliveries failed"],
            )
            self.assertEqual(database.pending_position_count(), 1)
            health = database.health(900)
            self.assertEqual(health["cycle_status"], "degraded")
            self.assertNotIn("SECRET_TOKEN", health["last_error"])

            logs = "\n".join(captured.output)
            self.assertIn("Relay cycle started", logs)
            self.assertIn(
                "Find Hub query failed device_id=bad error_type=TimeoutError", logs
            )
            self.assertIn("Find Hub query succeeded device_id=good reports=1", logs)
            summary = next(
                line for line in captured.output if "Relay cycle completed" in line
            )
            for fact in (
                "status=degraded",
                "devices_selected=2",
                "devices_queried=1",
                "positions_queued=1",
                "positions_sent=0",
                "delivery_failures=2",
                "pending_positions=1",
                "duration_seconds=",
            ):
                self.assertIn(fact, summary)
            for private_value in ("SECRET_TOKEN", "12.345", "67.89"):
                self.assertNotIn(private_value, logs)
                self.assertNotIn(private_value, str(result))

    async def test_normal_cycle_logs_query_and_complete_queue_state(self):
        class SuccessfulFindHub:
            async def list_devices(self):
                return [("Fake tracker", "device-normal")]

            async def locate(self, device_id):
                return [
                    {"time": 100, "latitude": 1, "longitude": 2},
                    {"time": 200, "latitude": 3, "longitude": 4},
                ]

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "relay.db")
            database.initialize()
            config = Config(
                traccar_url="http://example",
                poll_interval_seconds=900,
                location_timeout_seconds=30,
                device_refresh_interval_seconds=3600,
                device_ids=None,
                data_directory=Path(directory),
                credentials_file=Path(directory) / "credentials.json",
                log_level="INFO",
            )
            service = RelayService(
                config, database, SuccessfulFindHub(), FakeSender()
            )
            with self.assertLogs("findhub_relay.service", level="INFO") as captured:
                result = await service.run_cycle(force_refresh=True)

            self.assertEqual(result["status"], "ok")
            logs = "\n".join(captured.output)
            self.assertIn(
                "Find Hub query succeeded device_id=device-normal reports=2", logs
            )
            summary = next(
                line for line in captured.output if "Relay cycle completed" in line
            )
            for fact in (
                "status=ok",
                "devices_selected=1",
                "devices_queried=1",
                "positions_queued=2",
                "positions_sent=1",
                "delivery_failures=0",
                "pending_positions=2",
            ):
                self.assertIn(fact, summary)
            self.assertNotIn("latitude", logs)
            self.assertNotIn("longitude", logs)

    async def test_pending_count_failure_preserves_original_cycle_exception(self):
        original = RuntimeError("ORIGINAL_SECRET response=(12.345,67.89)")

        class FailingFindHub:
            async def list_devices(self):
                raise original

        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "relay.db")
            database.initialize()
            config = Config(
                traccar_url="http://example",
                poll_interval_seconds=900,
                location_timeout_seconds=30,
                device_refresh_interval_seconds=3600,
                device_ids=None,
                data_directory=Path(directory),
                credentials_file=Path(directory) / "credentials.json",
                log_level="INFO",
            )
            service = RelayService(config, database, FailingFindHub(), FakeSender())
            diagnostic_error = LookupError(
                "DIAGNOSTIC_SECRET endpoint=http://secret.invalid"
            )
            with patch.object(
                database,
                "pending_position_count",
                side_effect=diagnostic_error,
            ), self.assertLogs(
                "findhub_relay.service", level="INFO"
            ) as captured, self.assertRaises(
                RuntimeError
            ) as raised:
                await service.run_cycle(force_refresh=True)

            self.assertIs(raised.exception, original)
            logs = "\n".join(captured.output)
            self.assertIn("Relay cycle failed error_type=RuntimeError", logs)
            self.assertIn(
                "Relay cycle pending count failed error_type=LookupError", logs
            )
            summary = next(
                line for line in captured.output if "Relay cycle completed" in line
            )
            self.assertIn("status=failed", summary)
            self.assertIn("pending_positions=-1", summary)
            for private_value in (
                "ORIGINAL_SECRET",
                "DIAGNOSTIC_SECRET",
                "12.345",
                "67.89",
                "secret.invalid",
            ):
                self.assertNotIn(private_value, logs)

    async def test_daemon_logs_start_wait_and_graceful_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "relay.db")
            database.initialize()
            config = Config(
                traccar_url="http://example",
                poll_interval_seconds=900,
                location_timeout_seconds=30,
                device_refresh_interval_seconds=3600,
                device_ids=None,
                data_directory=Path(directory),
                credentials_file=Path(directory) / "credentials.json",
                log_level="INFO",
            )
            service = RelayService(config, database, FakeFindHub(), FakeSender())
            cycle_called = asyncio.Event()

            async def run_one_cycle(*, force_refresh=False):
                cycle_called.set()
                return {"status": "ok"}

            service.run_cycle = AsyncMock(side_effect=run_one_cycle)
            stop_event = asyncio.Event()
            with self.assertLogs("findhub_relay.service", level="INFO") as captured:
                daemon_task = asyncio.create_task(service.run_daemon(stop_event))
                await cycle_called.wait()
                stop_event.set()
                await daemon_task

            logs = "\n".join(captured.output)
            self.assertIn(
                "Relay daemon started poll_interval_seconds=900 device_filter=all",
                logs,
            )
            self.assertIn("Relay daemon waiting next_cycle_seconds=900", logs)
            self.assertIn("Relay daemon stopped gracefully", logs)
            service.run_cycle.assert_awaited_once_with(force_refresh=True)
            self.assertEqual(database.health(900)["daemon_status"], "stopped")


if __name__ == "__main__":
    unittest.main()
