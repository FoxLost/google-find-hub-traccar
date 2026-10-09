# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

from dataclasses import replace
import tempfile
from pathlib import Path
import unittest

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
            raise TimeoutError("no response")
        return [{"time": 123, "latitude": 1, "longitude": 2}]


class FakeSender:
    async def flush(self):
        return (1, 0)


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
            service = RelayService(config, database, findhub, FakeSender())
            result = await service.run_cycle(force_refresh=True)
            self.assertEqual(findhub.calls, ["bad", "good"])
            self.assertEqual(result["status"], "degraded")
            self.assertEqual(result["devices_queried"], 1)
            self.assertEqual(len(database.pending_positions()), 1)
            self.assertEqual(database.health(900)["cycle_status"], "degraded")


if __name__ == "__main__":
    unittest.main()
