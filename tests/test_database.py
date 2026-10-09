# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import tempfile
import os
from pathlib import Path
import unittest

from findhub_relay.database import Database


class DatabaseBehaviorTests(unittest.TestCase):
    def test_deduplicates_positions_and_queue_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "relay.db"
            first = Database(path)
            first.initialize()
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            reports = [
                {"time": 20, "latitude": 1.0, "longitude": 2.0},
                {"time": 10, "latitude": 3.0, "longitude": 4.0},
            ]
            self.assertEqual(first.enqueue_positions("device", reports), 2)
            self.assertEqual(first.enqueue_positions("device", reports), 0)

            restarted = Database(path)
            restarted.initialize()
            pending = restarted.pending_positions()
            self.assertEqual([row["timestamp"] for row in pending], [10, 20])
            restarted.mark_sent(pending[0]["id"])
            self.assertEqual(
                [row["timestamp"] for row in restarted.pending_positions()], [20]
            )


    def test_device_snapshot_removes_stale_devices_and_accepts_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "relay.db")
            database.initialize()
            database.replace_devices([
                ("Kept", "device-kept"),
                ("Removed", "device-removed"),
            ])
            database.replace_devices([("Renamed", "device-kept")])
            self.assertEqual(
                [(row["name"], row["device_id"]) for row in database.list_devices()],
                [("Renamed", "device-kept")],
            )
            database.replace_devices([])
            self.assertEqual(database.list_devices(), [])


if __name__ == "__main__":
    unittest.main()
