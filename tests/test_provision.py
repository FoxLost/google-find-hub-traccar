# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from findhub_relay.cli import _run
from findhub_relay.config import Config
from findhub_relay.database import Database


class _Fcm:
    stopped = False

    def __init__(self, database):
        self.database = database

    async def stop(self):
        type(self).stopped = True


class _FindHub:
    located = []

    def __init__(self, fcm, timeout):
        pass

    async def list_devices(self):
        return [("first", "device-1"), ("selected", "device-2")]

    async def locate(self, device_id):
        type(self).located.append(device_id)
        return []


class ProvisionBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_provision_queries_and_decrypts_configured_device_then_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            credentials_file = Path(directory) / "credentials.json"
            config = Config(
                traccar_url=None,
                poll_interval_seconds=900,
                location_timeout_seconds=30,
                device_refresh_interval_seconds=3600,
                device_ids=("device-2",),
                data_directory=Path(directory),
                credentials_file=credentials_file,
                log_level="INFO",
            )
            database = Database(config.database_path)
            database.initialize()

            def provision_aas():
                credentials_file.write_text(json.dumps({
                    "username": "user",
                    "aas_token": "aas",
                    "owner_key": "00",
                    "fcm_credentials": {
                        "gcm": {"android_id": "123"},
                        "fcm": {"registration": {"token": "registration"}},
                    },
                }), encoding="utf-8")

            _FindHub.located = []
            _Fcm.stopped = False
            with (
                patch("Auth.aas_token_retrieval.get_aas_token", side_effect=provision_aas),
                patch("findhub_relay.fcm.PersistentFcm", _Fcm),
                patch("findhub_relay.findhub.FindHubClient", _FindHub),
                patch(
                    "SpotApi.GetEidInfoForE2eeDevices.get_owner_key.get_owner_key",
                    return_value=b"key",
                ),
            ):
                self.assertEqual(await _run("provision", config, database), 0)
            self.assertEqual(_FindHub.located, ["device-2"])
            self.assertTrue(_Fcm.stopped)


if __name__ == "__main__":
    unittest.main()
