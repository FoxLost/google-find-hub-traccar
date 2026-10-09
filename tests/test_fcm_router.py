# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import asyncio
import unittest

from findhub_relay.fcm import RequestRouter


class RequestRouterBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_only_matching_uuid_and_cleans_success(self):
        router = RequestRouter()

        async def send():
            self.assertFalse(router.dispatch("other", "wrong"))
            self.assertTrue(router.dispatch("wanted", "response"))

        self.assertEqual(await router.wait_for("wanted", send, 0.2), "response")
        self.assertEqual(router.pending_count, 0)
        self.assertFalse(router.dispatch("wanted", "late"))

    async def test_timeout_and_cancellation_clean_pending_future(self):
        router = RequestRouter()
        with self.assertRaises(asyncio.TimeoutError):
            await router.wait_for("timeout", lambda: None, 0.01)
        self.assertEqual(router.pending_count, 0)

        async def slow_send():
            await asyncio.sleep(1)

        with self.assertRaises(asyncio.TimeoutError):
            await router.wait_for("slow-send", slow_send, 0.01)
        self.assertEqual(router.pending_count, 0)
        self.assertFalse(router.dispatch("slow-send", "late"))

        task = asyncio.create_task(router.wait_for("cancel", lambda: None, 10))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(router.pending_count, 0)


if __name__ == "__main__":
    unittest.main()
