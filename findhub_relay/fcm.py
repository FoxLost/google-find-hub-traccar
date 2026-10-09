#
# GoogleFindMyTools - A set of tools to interact with the Google Find My API
# Copyright © 2024 Leon Böttger. All rights reserved.
#
"""Persistent FCM/MCS listener and request UUID response routing."""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import inspect
from typing import Callable

from Auth.firebase_messaging import (
    FcmPushClient,
    FcmPushClientRunState,
    FcmRegisterConfig,
)
from Auth.token_cache import get_cached_value, set_cached_value
from ProtoDecoders.decoder import parse_device_update_protobuf

from .database import Database

LOGGER = logging.getLogger(__name__)

FCM_CONFIG = FcmRegisterConfig(
    project_id="google.com:api-project-289722593072",
    app_id="1:289722593072:android:3cfcf5bc359f0308",
    api_key="AIzaSyD_gko3P392v6how2H7UpdeXQ0v2HLettc",
    messaging_sender_id="289722593072",
    bundle_id="com.google.android.apps.adm",
    android_package="com.google.android.apps.adm",
    android_cert_sha1="38918A453D07199354F8B19AF05EC6562CED5788",
)


class RequestRouter:
    """Own futures for in-flight requests and remove them on every exit path."""

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future] = {}

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    async def wait_for(
        self,
        request_uuid: str,
        send: Callable[[], object],
        timeout: float,
    ):
        if request_uuid in self._pending:
            raise RuntimeError(f"duplicate in-flight request UUID {request_uuid}")
        future = asyncio.get_running_loop().create_future()
        self._pending[request_uuid] = future
        async def send_and_receive():
            result = send()
            if inspect.isawaitable(result):
                await result
            return await future

        try:
            return await asyncio.wait_for(send_and_receive(), timeout)
        finally:
            self._pending.pop(request_uuid, None)
            if not future.done():
                future.cancel()

    def dispatch(self, request_uuid: str, response) -> bool:
        future = self._pending.get(request_uuid)
        if future is None or future.done():
            return False
        future.set_result(response)
        return True

    def cancel_all(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()


class PersistentFcm:
    def __init__(self, database: Database, readiness_timeout: float = 30):
        self.database = database
        self.readiness_timeout = readiness_timeout
        self.router = RequestRouter()
        credentials = database.load_fcm_credentials() or get_cached_value("fcm_credentials")
        self.client = FcmPushClient(
            self._on_notification,
            FCM_CONFIG,
            credentials,
            self._on_credentials_updated,
        )
        self._started = False
        self._start_lock = asyncio.Lock()

    def _on_credentials_updated(self, credentials: dict) -> None:
        self.database.save_fcm_credentials(credentials)
        # Keep the legacy auth helpers on the same mutable registration state.
        set_cached_value("fcm_credentials", credentials)
        LOGGER.info("FCM credentials updated")

    def _on_notification(self, obj, notification, data_message) -> None:
        payload = obj.get("data", {}).get("com.google.android.apps.adm.FCM_PAYLOAD")
        if not payload:
            LOGGER.debug("Ignoring FCM notification without Find Hub payload")
            return
        try:
            response_hex = binascii.hexlify(base64.b64decode(payload)).decode("ascii")
            update = parse_device_update_protobuf(response_hex)
            request_uuid = update.fcmMetadata.requestUuid
        except Exception:
            LOGGER.exception("Unable to parse FCM Find Hub response")
            return
        if not self.router.dispatch(request_uuid, update):
            LOGGER.debug("Ignoring response for unknown request UUID")

    def _listener_alive(self) -> bool:
        tasks = getattr(self.client, "tasks", ())
        # FcmPushClient stores the MCS listener first and its monitor second.
        # A live monitor must not disguise a listener which exhausted reconnects.
        listener = tasks[0] if tasks else None
        return bool(
            self._started
            and getattr(self.client, "do_listen", False)
            and listener is not None
            and not listener.done()
        )

    async def _wait_until_ready(self) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.readiness_timeout
        while loop.time() < deadline:
            if self.client.run_state == FcmPushClientRunState.STARTED:
                return
            if not self._listener_alive():
                raise ConnectionError("FCM/MCS listener stopped before login completed")
            await asyncio.sleep(0.05)
        raise TimeoutError("FCM/MCS login did not become ready before timeout")

    async def ensure_started(self) -> str:
        async with self._start_lock:
            if not self._listener_alive():
                if self._started:
                    await self.client.stop()
                    self._started = False
                token = await self.client.checkin_or_register()
                # checkin_or_register can mutate credentials without invoking the
                # callback when credentials already existed.
                self._on_credentials_updated(self.client.credentials)
                await self.client.start()
                self._started = True
            else:
                token = self.client.credentials["fcm"]["registration"]["token"]
            try:
                await self._wait_until_ready()
            except Exception:
                await self.client.stop()
                self._started = False
                raise
            return token

    async def stop(self) -> None:
        self.router.cancel_all()
        if self._started:
            await self.client.stop()
            self._started = False
