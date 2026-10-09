# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import (
    IdentityKeyDecryptionError,
    retrieve_identity_key,
)


class IdentityKeyFailureTests(unittest.TestCase):
    def test_decrypt_failure_raises_normal_exception_not_system_exit(self):
        registration = SimpleNamespace(
            fastPairModelId="model",
            encryptedUserSecrets=SimpleNamespace(
                encryptedIdentityKey=b"encrypted",
                ownerKeyVersion=1,
            ),
        )
        eid_info = SimpleNamespace(
            encryptedOwnerKeyAndMetadata=SimpleNamespace(ownerKeyVersion=2)
        )
        with (
            patch(
                "NovaApi.ExecuteAction.LocateTracker.decrypt_locations.flip_bits",
                return_value=b"encrypted",
            ),
            patch(
                "NovaApi.ExecuteAction.LocateTracker.decrypt_locations.get_owner_key",
                return_value=b"owner-key",
            ),
            patch(
                "NovaApi.ExecuteAction.LocateTracker.decrypt_locations.decrypt_eik",
                side_effect=ValueError("cryptographic failure"),
            ),
            patch(
                "NovaApi.ExecuteAction.LocateTracker.decrypt_locations.get_eid_info",
                return_value=eid_info,
            ),
        ):
            with self.assertRaises(IdentityKeyDecryptionError) as raised:
                retrieve_identity_key(registration)
        self.assertIn("obsolete owner key version 1", str(raised.exception))
        self.assertNotIsInstance(raised.exception, SystemExit)


if __name__ == "__main__":
    unittest.main()
