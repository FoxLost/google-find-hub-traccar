# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import unittest
from unittest.mock import patch

from NovaApi.nova_request import NovaRequestError, nova_request


class _Response:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content
        self.text = "sensitive server response"


class NovaTransportTests(unittest.TestCase):
    @patch("NovaApi.nova_request.get_username", return_value="user")
    @patch("NovaApi.nova_request.get_adm_token", return_value="secret-token")
    def test_uses_bounded_timeout_and_android_headers(self, token, username):
        with patch(
            "NovaApi.nova_request.requests.post",
            return_value=_Response(200, b"ok"),
        ) as post:
            self.assertEqual(nova_request("scope", "00"), b"ok".hex())
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["timeout"], 30)
        self.assertEqual(kwargs["headers"]["X-Android-Package"], "com.google.android.apps.adm")
        self.assertEqual(
            kwargs["headers"]["X-Android-Cert"],
            "38918A453D07199354F8B19AF05EC6562CED5788",
        )

    @patch("NovaApi.nova_request.get_username", return_value="user")
    @patch("NovaApi.nova_request.get_adm_token", return_value="secret-token")
    def test_non_2xx_raises_without_response_body(self, token, username):
        with patch(
            "NovaApi.nova_request.requests.post", return_value=_Response(403)
        ):
            with self.assertRaises(NovaRequestError) as raised:
                nova_request("scope", "00")
        self.assertNotIn("sensitive", str(raised.exception))
        self.assertIn("403", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
