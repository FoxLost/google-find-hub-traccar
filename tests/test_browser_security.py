# Copyright © 2024 Leon Böttger. Licensed under GPL-3.0.

import json
import os
import unittest
from unittest.mock import Mock, call, patch

from selenium.common.exceptions import NoAlertPresentException, TimeoutException

import chrome_driver
from KeyBackup import shared_key_flow


class ChromeDriverTests(unittest.TestCase):
    def test_find_chrome_expands_windows_username_candidate(self):
        expected = r"C:\Users\alice\AppData\Local\Google\Chrome\Application\chrome.exe"
        with (
            patch.dict(os.environ, {"USERNAME": "alice"}, clear=True),
            patch("chrome_driver.os.path.exists", side_effect=lambda path: path == expected),
        ):
            self.assertEqual(chrome_driver.find_chrome(), expected)

    def test_find_chrome_expands_home_candidate(self):
        expected = "/home/alice/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        with (
            patch("chrome_driver.os.path.expanduser", side_effect=lambda path: path.replace("~", "/home/alice")),
            patch("chrome_driver.os.path.exists", side_effect=lambda path: path == expected),
        ):
            self.assertEqual(chrome_driver.find_chrome(), expected)

    def test_no_sandbox_requires_explicit_opt_in(self):
        options = Mock()
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("chrome_driver.uc.ChromeOptions", return_value=options),
        ):
            chrome_driver.get_options()
        self.assertNotIn(call("--no-sandbox"), options.add_argument.call_args_list)

        options.reset_mock()
        with (
            patch.dict(os.environ, {"CHROME_NO_SANDBOX": "1"}, clear=True),
            patch("chrome_driver.uc.ChromeOptions", return_value=options),
        ):
            chrome_driver.get_options()
        self.assertIn(call("--no-sandbox"), options.add_argument.call_args_list)


class SharedKeyFlowTests(unittest.TestCase):
    def test_alert_condition_ignores_only_absent_alert(self):
        class SwitchTo:
            @property
            def alert(self):
                raise NoAlertPresentException()

        driver = Mock()
        driver.switch_to = SwitchTo()
        self.assertFalse(shared_key_flow._shared_key_from_alert(driver))

    def test_success_returns_key_and_quits_once(self):
        driver = Mock()
        alert = Mock()
        alert.text = json.dumps({"method": "setVaultSharedKeys", "vaultKeys": ["key"]})
        driver.switch_to.alert = alert
        login_wait = Mock()
        login_wait.until.return_value = True
        alert_wait = Mock()
        alert_wait.until.side_effect = lambda condition: condition(driver)

        with (
            patch("KeyBackup.shared_key_flow.create_driver", return_value=driver),
            patch(
                "KeyBackup.shared_key_flow.get_security_domain_request_url",
                return_value="https://example.invalid/unlock",
            ),
            patch(
                "KeyBackup.shared_key_flow.get_fmdn_shared_key",
                return_value=b"shared-key",
            ),
            patch(
                "KeyBackup.shared_key_flow.WebDriverWait",
                side_effect=[login_wait, alert_wait],
            ) as waits,
        ):
            self.assertEqual(
                shared_key_flow.request_shared_key_flow(), b"shared-key".hex()
            )

        self.assertEqual([item.args[1] for item in waits.call_args_list], [300, 300])
        alert.accept.assert_called_once_with()
        driver.quit.assert_called_once_with()

    def test_malformed_alert_propagates_and_quits(self):
        driver = Mock()
        alert = Mock(text="not-json")
        driver.switch_to.alert = alert
        login_wait = Mock()
        login_wait.until.return_value = True
        alert_wait = Mock()
        alert_wait.until.side_effect = lambda condition: condition(driver)

        with (
            patch("KeyBackup.shared_key_flow.create_driver", return_value=driver),
            patch("KeyBackup.shared_key_flow.get_security_domain_request_url", return_value="https://example.invalid/unlock"),
            patch("KeyBackup.shared_key_flow.WebDriverWait", side_effect=[login_wait, alert_wait]),
            self.assertRaises(json.JSONDecodeError),
        ):
            shared_key_flow.request_shared_key_flow()
        driver.quit.assert_called_once_with()

    def test_timeout_propagates_and_quits(self):
        driver = Mock()
        login_wait = Mock()
        login_wait.until.return_value = True
        alert_wait = Mock()
        alert_wait.until.side_effect = TimeoutException("timed out")

        with (
            patch("KeyBackup.shared_key_flow.create_driver", return_value=driver),
            patch("KeyBackup.shared_key_flow.get_security_domain_request_url", return_value="https://example.invalid/unlock"),
            patch("KeyBackup.shared_key_flow.WebDriverWait", side_effect=[login_wait, alert_wait]),
            self.assertRaises(TimeoutException),
        ):
            shared_key_flow.request_shared_key_flow()
        driver.quit.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
