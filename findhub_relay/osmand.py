#
# GoogleFindMyTools - A set of tools to interact with the Google Find My API
# Copyright © 2024 Leon Böttger. All rights reserved.
#
"""Durable OsmAnd protocol queue delivery."""

from __future__ import annotations

import asyncio
import logging
import requests

from .database import Database

LOGGER = logging.getLogger(__name__)
OUTBOUND_BATCH_SIZE = 1000


class OsmandSender:
    def __init__(self, database: Database, url: str, timeout: int = 30):
        self.database = database
        self.url = url
        self.timeout = timeout

    def _send_one(self, session: requests.Session, position: dict) -> int:
        response = session.post(
            self.url,
            data={
                "id": position["device_id"],
                "lat": position["latitude"],
                "lon": position["longitude"],
                "timestamp": position["timestamp"],
                "accuracy": position["accuracy"],
                "altitude": position["altitude"],
                "valid": "true" if position["valid"] else "false",
                "source": position["source"],
                "reportType": position["report_type"],
            },
            timeout=self.timeout,
        )
        return response.status_code

    async def flush(self) -> tuple[int, int]:
        sent = 0
        failed = 0
        with requests.Session() as session:
            for position in self.database.pending_positions(OUTBOUND_BATCH_SIZE):
                try:
                    status_code = await asyncio.to_thread(
                        self._send_one, session, position
                    )
                except requests.RequestException as exc:
                    LOGGER.warning(
                        "OsmAnd delivery transport failure device_id=%s "
                        "position_timestamp=%s error_type=%s",
                        position["device_id"],
                        position["timestamp"],
                        type(exc).__name__,
                    )
                    failed += 1
                    break
                if 200 <= status_code < 300:
                    self.database.mark_sent(position["id"])
                    sent += 1
                    LOGGER.info(
                        "OsmAnd delivery accepted device_id=%s "
                        "position_timestamp=%s http_status=%s",
                        position["device_id"],
                        position["timestamp"],
                        status_code,
                    )
                    continue
                failed += 1
                LOGGER.warning(
                    "OsmAnd delivery HTTP failure device_id=%s "
                    "position_timestamp=%s http_status=%s",
                    position["device_id"],
                    position["timestamp"],
                    status_code,
                )
                if status_code == 429 or status_code >= 500:
                    break
        return sent, failed
