# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import asyncio
import unittest

from Auth.firebase_messaging.fcmregister import FcmRegister, FcmRegisterConfig
from Auth.fcm_receiver import FcmReceiver
from findhub_relay.fcm import FCM_CONFIG, PersistentFcm
from Auth.firebase_messaging import FcmPushClientRunState


class _Response:
    status = 200

    async def json(self):
        return {
            "authToken": {"token": "install-token", "expiresIn": "3600s"},
            "refreshToken": "refresh-token",
            "fid": "fid",
            "name": "registration",
        }

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, **kwargs):
        self.calls.append(kwargs)
        return _Response()


class ConfigRegressionTests(unittest.TestCase):
    def test_persistent_id_defaults_are_not_shared(self):
        first = FcmRegisterConfig("project", "app", "key", "sender")
        second = FcmRegisterConfig("project", "app", "key", "sender")
        first.persistend_ids.append("message")
        self.assertEqual(second.persistend_ids, [])

    def test_legacy_provisioning_receiver_sets_android_identity(self):
        FcmReceiver._instance = None
        receiver = FcmReceiver()
        config = receiver.pc.fcm_config
        self.assertEqual(config.android_package, "com.google.android.apps.adm")
        self.assertEqual(
            config.android_cert_sha1,
            "38918A453D07199354F8B19AF05EC6562CED5788",
        )


class RegistrationHeaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_install_and_registration_send_android_identity_headers(self):
        session = _Session()
        register = FcmRegister(FCM_CONFIG, http_client_session=session)
        installation = await register.fcm_install()
        await register.fcm_register(
            {"token": "gcm"}, installation, {"secret": "s", "public": "p"}
        )
        self.assertEqual(len(session.calls), 2)
        for call in session.calls:
            self.assertEqual(
                call["headers"]["X-Android-Package"],
                "com.google.android.apps.adm",
            )
            self.assertEqual(
                call["headers"]["X-Android-Cert"],
                "38918A453D07199354F8B19AF05EC6562CED5788",
            )


class _FakePushClient:
    def __init__(self):
        self.credentials = {"fcm": {"registration": {"token": "token"}}}
        self.run_state = FcmPushClientRunState.CREATED
        self.do_listen = False
        self.tasks = []
        self.starts = 0
        self.stops = 0
        self.checkins = 0

    async def checkin_or_register(self):
        self.checkins += 1
        return "token"

    async def start(self):
        self.starts += 1
        self.do_listen = True
        self.tasks = [asyncio.create_task(asyncio.sleep(60))]
        asyncio.get_running_loop().call_soon(
            setattr, self, "run_state", FcmPushClientRunState.STARTED
        )

    async def stop(self):
        self.stops += 1
        self.do_listen = False
        self.run_state = FcmPushClientRunState.STOPPED
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)


class FcmReadinessTests(unittest.IsolatedAsyncioTestCase):
    def relay(self):
        relay = PersistentFcm.__new__(PersistentFcm)
        relay.client = _FakePushClient()
        relay.readiness_timeout = 0.5
        relay._started = False
        relay._start_lock = asyncio.Lock()
        relay._on_credentials_updated = lambda credentials: None
        return relay

    async def test_waits_for_started_and_reuses_ready_listener(self):
        relay = self.relay()
        self.assertEqual(await relay.ensure_started(), "token")
        self.assertEqual(relay.client.run_state, FcmPushClientRunState.STARTED)
        self.assertEqual(await relay.ensure_started(), "token")
        self.assertEqual(relay.client.starts, 1)
        await relay.client.stop()

    async def test_restarts_when_listener_task_is_dead(self):
        relay = self.relay()
        await relay.ensure_started()
        relay.client.tasks[0].cancel()
        await asyncio.gather(relay.client.tasks[0], return_exceptions=True)
        self.assertEqual(await relay.ensure_started(), "token")
        self.assertEqual(relay.client.starts, 2)
        self.assertGreaterEqual(relay.client.stops, 1)
        await relay.client.stop()


if __name__ == "__main__":
    unittest.main()
