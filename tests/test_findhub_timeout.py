# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import asyncio
import time
import unittest
from unittest.mock import patch

from findhub_relay.findhub import FindHubClient


class _UnusedRouter:
    async def wait_for(self, *args):
        raise AssertionError("router must not run before FCM readiness")


class _SlowFcm:
    router = _UnusedRouter()

    async def ensure_started(self):
        await asyncio.sleep(1)
        return "token"


class _ImmediateRouter:
    async def wait_for(self, request_uuid, send, timeout):
        return object()


class _ReadyFcm:
    router = _ImmediateRouter()

    async def ensure_started(self):
        return "token"


class FindHubTotalTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_devices_times_out_slow_sync_request(self):
        def slow_list():
            time.sleep(0.1)
            return "unused"

        client = FindHubClient(_ReadyFcm(), 0.01)
        with patch("findhub_relay.findhub.request_device_list", side_effect=slow_list):
            with self.assertRaises(asyncio.TimeoutError):
                await client.list_devices()

    async def test_locate_timeout_includes_fcm_readiness(self):
        client = FindHubClient(_SlowFcm(), 0.01)
        with self.assertRaises(asyncio.TimeoutError):
            await client.locate("device")

    async def test_locate_timeout_includes_sync_decryption(self):
        def slow_decrypt(update):
            time.sleep(0.1)
            return []

        client = FindHubClient(_ReadyFcm(), 0.01)
        with (
            patch("findhub_relay.findhub.create_location_request", return_value="payload"),
            patch("findhub_relay.findhub.extract_locations", side_effect=slow_decrypt),
        ):
            with self.assertRaises(asyncio.TimeoutError):
                await client.locate("device")


if __name__ == "__main__":
    unittest.main()
