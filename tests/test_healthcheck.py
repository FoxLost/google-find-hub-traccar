# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import io
import json
import os
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch

from findhub_relay.cli import main
from findhub_relay.database import Database


class HealthcheckBehaviorTests(unittest.TestCase):
    def run_healthcheck(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["healthcheck"])
        return status, json.loads(output.getvalue())

    def test_requires_running_daemon_and_fresh_successful_cycle(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"DATA_DIRECTORY": directory, "POLL_INTERVAL_SECONDS": "10"},
            clear=True,
        ):
            status, report = self.run_healthcheck()
            self.assertEqual(status, 1)
            self.assertFalse(report["healthy"])
            self.assertTrue(report["stale"])

            database = Database(Path(directory) / "relay.db")
            database.set_health(
                daemon_status="running",
                cycle_status="ok",
                cycle_finished_at=int(time.time()),
            )
            status, report = self.run_healthcheck()
            self.assertEqual(status, 0)
            self.assertTrue(report["healthy"])

            database.set_health(cycle_status="degraded", last_error="one failed")
            status, report = self.run_healthcheck()
            self.assertEqual(status, 1)
            self.assertFalse(report["healthy"])

            database.set_health(
                cycle_status="ok", cycle_finished_at=int(time.time()) - 21
            )
            status, report = self.run_healthcheck()
            self.assertEqual(status, 1)
            self.assertTrue(report["stale"])


if __name__ == "__main__":
    unittest.main()
