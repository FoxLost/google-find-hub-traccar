# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import builtins
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from Auth.token_retrieval import get_android_id
from findhub_relay.cli import _validate_credentials
from findhub_relay.config import Config
from SpotApi.GetEidInfoForE2eeDevices.get_owner_key import get_owner_key


class RuntimeDependencyTests(unittest.TestCase):
    def test_runtime_requirements_exclude_browser_dependencies_and_are_pinned(self):
        lines = Path("requirements-runtime.txt").read_text(encoding="utf-8").splitlines()
        self.assertFalse(any("selenium" in line.lower() for line in lines))
        self.assertFalse(any("undetected" in line.lower() for line in lines))
        self.assertFalse(any("beautifulsoup" in line.lower() for line in lines))
        self.assertTrue(lines)
        self.assertTrue(all("==" in line for line in lines))

    def test_runtime_modules_import_when_browser_imports_are_blocked(self):
        original_import = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name == "selenium" or name.startswith("selenium.") or name == "undetected_chromedriver":
                raise AssertionError(f"runtime imported browser dependency {name}")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=guarded):
            importlib.reload(importlib.import_module("Auth.aas_token_retrieval"))
            importlib.reload(importlib.import_module("KeyBackup.shared_key_retrieval"))
            importlib.reload(importlib.import_module("findhub_relay.findhub"))


class CredentialBehaviorTests(unittest.TestCase):
    def config(self, directory):
        return Config(
            traccar_url=None,
            poll_interval_seconds=900,
            location_timeout_seconds=30,
            device_refresh_interval_seconds=3600,
            device_ids=None,
            data_directory=Path(directory),
            credentials_file=Path(directory) / "credentials.json",
            log_level="INFO",
        )

    def test_android_id_uses_cache_without_legacy_receiver(self):
        with patch(
            "Auth.token_retrieval.get_cached_value",
            return_value={"gcm": {"android_id": "12345"}},
        ):
            self.assertEqual(get_android_id(), "12345")

    def test_cached_owner_key_does_not_enter_shared_key_flow(self):
        with (
            patch(
                "SpotApi.GetEidInfoForE2eeDevices.get_owner_key.get_cached_value",
                return_value="00",
            ),
            patch(
                "SpotApi.GetEidInfoForE2eeDevices.get_owner_key._retrieve_owner_key",
                side_effect=AssertionError("shared-key flow must stay lazy"),
            ),
        ):
            self.assertEqual(get_owner_key(), b"\x00")

    def test_validation_requires_complete_runtime_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(directory)
            incomplete = {"username": "user", "aas_token": "token"}
            config.credentials_file.write_text(json.dumps(incomplete), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "owner_key"):
                _validate_credentials(config)

            complete = {
                "username": "user",
                "aas_token": "token",
                "owner_key": "00",
                "fcm_credentials": {
                    "gcm": {"android_id": "123"},
                    "fcm": {"registration": {"token": "registration"}},
                },
            }
            config.credentials_file.write_text(json.dumps(complete), encoding="utf-8")
            _validate_credentials(config)


if __name__ == "__main__":
    unittest.main()
