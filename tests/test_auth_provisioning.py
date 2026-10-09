# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import os
import unittest
from unittest.mock import Mock, call, patch

from Auth.aas_token_retrieval import _generate_aas_token, _provisioning_username


class FreshAccountProvisioningTests(unittest.TestCase):
    def test_google_username_is_persisted_before_exchange_and_response_is_authoritative(self):
        receiver = Mock()
        receiver.get_android_id.return_value = "android-id"
        with (
            patch.dict(os.environ, {"GOOGLE_USERNAME": "entered@example.com"}, clear=False),
            patch("Auth.aas_token_retrieval.get_username", return_value=""),
            patch("Auth.aas_token_retrieval.set_cached_value") as save,
            patch(
                "Auth.auth_flow.request_oauth_account_token_flow",
                return_value="browser-token",
            ),
            patch("Auth.fcm_receiver.FcmReceiver", return_value=receiver),
            patch(
                "Auth.aas_token_retrieval.gpsoauth.exchange_token",
                return_value={"Token": "aas", "Email": "canonical@example.com"},
            ) as exchange,
        ):
            self.assertEqual(_generate_aas_token(), "aas")
        exchange.assert_called_once_with(
            "entered@example.com", "browser-token", "android-id"
        )
        self.assertEqual(
            save.call_args_list,
            [call("username", "entered@example.com"), call("username", "canonical@example.com")],
        )

    def test_fresh_path_prompts_and_rejects_empty_email(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("Auth.aas_token_retrieval.get_username", return_value=""),
            patch("builtins.input", return_value="   "),
            patch("Auth.aas_token_retrieval.set_cached_value") as save,
        ):
            with self.assertRaisesRegex(RuntimeError, "must not be empty"):
                _provisioning_username()
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
