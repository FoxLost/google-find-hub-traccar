# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import asyncio
import tempfile
from pathlib import Path
import unittest
import requests
from unittest.mock import patch

from findhub_relay.database import Database
from findhub_relay.osmand import OsmandSender


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


class OsmandBehaviorTests(unittest.TestCase):
    def test_non_2xx_is_retained_and_later_2xx_marks_sent(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "relay.db")
            database.initialize()
            database.enqueue_positions("tracker", [{
                "time": 100,
                "latitude": 1.5,
                "longitude": 2.5,
                "accuracy": 4,
                "altitude": 5,
                "is_own_report": True,
            }])
            sender = OsmandSender(database, "http://traccar.example/")
            with patch("findhub_relay.osmand.requests.Session") as session_factory:
                post = session_factory.return_value.__enter__.return_value.post
                post.return_value = _Response(503)
                self.assertEqual(asyncio.run(sender.flush()), (0, 1))
                self.assertEqual(len(database.pending_positions()), 1)
                payload = post.call_args.kwargs["data"]
                self.assertEqual(
                    set(payload),
                    {"id", "lat", "lon", "timestamp", "accuracy", "altitude", "valid", "source", "reportType"},
                )
                post.reset_mock()
                post.return_value = _Response(204)
                self.assertEqual(asyncio.run(sender.flush()), (1, 0))
                self.assertEqual(post.call_count, 1)
                self.assertEqual(database.pending_positions(), [])


    def test_flush_processes_only_one_bounded_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "relay.db")
            database.initialize()
            database.enqueue_positions(
                "tracker",
                [
                    {"time": timestamp, "latitude": 1.0, "longitude": 2.0}
                    for timestamp in range(1, 1002)
                ],
            )
            sender = OsmandSender(database, "http://traccar.example/")
            with patch("findhub_relay.osmand.requests.Session") as session_factory:
                post = session_factory.return_value.__enter__.return_value.post
                post.return_value = _Response(204)
                self.assertEqual(asyncio.run(sender.flush()), (1000, 0))
                self.assertEqual(post.call_count, 1000)
                self.assertEqual(database.health(900)["pending_positions"], 1)
                self.assertEqual(asyncio.run(sender.flush()), (1, 0))
                self.assertEqual(post.call_count, 1001)


    def test_endpoint_failures_stop_batch_but_client_4xx_does_not(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "relay.db")
            database.initialize()
            database.enqueue_positions(
                "tracker",
                [
                    {"time": timestamp, "latitude": 1.0, "longitude": 2.0}
                    for timestamp in range(1, 4)
                ],
            )
            sender = OsmandSender(database, "http://traccar.example/")
            with patch("findhub_relay.osmand.requests.Session") as session_factory:
                post = session_factory.return_value.__enter__.return_value.post
                post.return_value = _Response(503)
                self.assertEqual(asyncio.run(sender.flush()), (0, 1))
                self.assertEqual(post.call_count, 1)
                self.assertEqual(database.health(900)["pending_positions"], 3)

                post.reset_mock()
                post.side_effect = requests.ConnectionError("offline")
                self.assertEqual(asyncio.run(sender.flush()), (0, 1))
                self.assertEqual(post.call_count, 1)
                self.assertEqual(database.health(900)["pending_positions"], 3)

                post.reset_mock()
                post.side_effect = [_Response(400), _Response(204), _Response(204)]
                self.assertEqual(asyncio.run(sender.flush()), (2, 1))
                self.assertEqual(post.call_count, 3)
                pending = database.pending_positions()
                self.assertEqual([item["timestamp"] for item in pending], [1])

    def test_delivery_logs_success_http_failure_and_safe_transport_type(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "relay.db")
            database.initialize()
            database.enqueue_positions(
                "device-log-test",
                [
                    {"time": timestamp, "latitude": 12.345, "longitude": 67.89}
                    for timestamp in range(101, 104)
                ],
            )
            sender = OsmandSender(
                database, "http://fake-secret-endpoint.invalid/?token=DO_NOT_LOG"
            )
            with patch("findhub_relay.osmand.requests.Session") as session_factory:
                post = session_factory.return_value.__enter__.return_value.post
                post.side_effect = [
                    _Response(202),
                    _Response(400),
                    requests.ConnectionError(
                        "SECRET_TOKEN response=(12.345,67.89)"
                    ),
                ]
                with self.assertLogs("findhub_relay.osmand", level="INFO") as captured:
                    self.assertEqual(asyncio.run(sender.flush()), (1, 2))

            accepted = next(line for line in captured.output if "accepted" in line)
            self.assertIn("device_id=device-log-test", accepted)
            self.assertIn("position_timestamp=101", accepted)
            self.assertIn("http_status=202", accepted)

            http_failure = next(
                line for line in captured.output if "HTTP failure" in line
            )
            self.assertIn("device_id=device-log-test", http_failure)
            self.assertIn("position_timestamp=102", http_failure)
            self.assertIn("http_status=400", http_failure)

            transport_failure = next(
                line for line in captured.output if "transport failure" in line
            )
            self.assertIn("device_id=device-log-test", transport_failure)
            self.assertIn("position_timestamp=103", transport_failure)
            self.assertIn("error_type=ConnectionError", transport_failure)

            all_logs = "\n".join(captured.output)
            for private_value in (
                "12.345",
                "67.89",
                "fake-secret-endpoint",
                "DO_NOT_LOG",
                "SECRET_TOKEN",
            ):
                self.assertNotIn(private_value, all_logs)


if __name__ == "__main__":
    unittest.main()
