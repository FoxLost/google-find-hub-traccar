#
# GoogleFindMyTools - A set of tools to interact with the Google Find My API
# Copyright © 2024 Leon Böttger. All rights reserved.
#
"""Async facade over the upstream synchronous Google Find Hub calls."""

from __future__ import annotations

import asyncio
import logging

from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import extract_locations
from NovaApi.ExecuteAction.LocateTracker.location_request import create_location_request
from NovaApi.ListDevices.nbe_list_devices import request_device_list
from NovaApi.nova_request import nova_request
from NovaApi.scopes import NOVA_ACTION_API_SCOPE
from NovaApi.util import generate_random_uuid
from ProtoDecoders.decoder import get_canonic_ids, parse_device_list_protobuf

from .fcm import PersistentFcm

LOGGER = logging.getLogger(__name__)


class FindHubClient:
    def __init__(self, fcm: PersistentFcm, location_timeout: int):
        self.fcm = fcm
        self.location_timeout = location_timeout

    async def list_devices(self) -> list[tuple[str, str]]:
        response = await asyncio.wait_for(
            asyncio.to_thread(request_device_list),
            timeout=self.location_timeout,
        )
        if not response:
            raise RuntimeError("Google Find Hub device list request failed")
        return get_canonic_ids(parse_device_list_protobuf(response))

    async def locate(self, device_id: str) -> list[dict]:
        async def operation() -> list[dict]:
            token = await self.fcm.ensure_started()
            request_uuid = generate_random_uuid()
            payload = create_location_request(device_id, token, request_uuid)

            async def send() -> None:
                response = await asyncio.to_thread(
                    nova_request, NOVA_ACTION_API_SCOPE, payload
                )
                if response is None:
                    raise RuntimeError("Google Find Hub location request was rejected")

            update = await self.fcm.router.wait_for(
                request_uuid, send, self.location_timeout
            )
            locations = await asyncio.to_thread(extract_locations, update)
            return sorted(
                (
                    location
                    for location in locations
                    if "latitude" in location and "longitude" in location
                ),
                key=lambda location: int(location["time"]),
            )

        return await asyncio.wait_for(
            operation(),
            timeout=self.location_timeout,
        )
