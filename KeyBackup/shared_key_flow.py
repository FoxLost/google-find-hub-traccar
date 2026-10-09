#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import json

from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as ec

from KeyBackup.response_parser import get_fmdn_shared_key
from KeyBackup.shared_key_request import get_security_domain_request_url
from chrome_driver import create_driver

def _shared_key_from_alert(driver):
    """Consume a vault callback alert, or keep waiting when no alert exists."""
    alert = ec.alert_is_present()(driver)
    if not alert:
        return False

    message = alert.text
    alert.accept()
    data = json.loads(message)
    method = data["method"]
    if method == "setVaultSharedKeys":
        return get_fmdn_shared_key(data["vaultKeys"]).hex()
    if method == "closeView":
        raise RuntimeError("Google security-domain flow closed without a shared key")
    raise RuntimeError(f"Unexpected Google security-domain callback: {method}")


def request_shared_key_flow():
    driver = create_driver()
    try:
        # Open Google accounts sign-in page
        driver.get("https://accounts.google.com/")

        # Wait for user to sign in and redirect to https://myaccount.google.com
        WebDriverWait(driver, 300).until(
            ec.url_contains("https://myaccount.google.com")
        )
        print("[SharedKeyFlow] Signed in successfully.")

        # Open the security domain request URL
        security_url = get_security_domain_request_url()
        driver.get(security_url)

        # Inject JavaScript interface
        script = """
        window.mm = {
            setVaultSharedKeys: function(str, vaultKeys) {
                console.log('setVaultSharedKeys called with:', str, vaultKeys);
                alert(JSON.stringify({ method: 'setVaultSharedKeys', str: str, vaultKeys: vaultKeys }));
            },
            closeView: function() {
                console.log('closeView called');
                alert(JSON.stringify({ method: 'closeView' }));
            }
        };
        """
        driver.execute_script(script)

        shared_key = WebDriverWait(driver, 300).until(_shared_key_from_alert)
        print("[SharedKeyFlow] Received Shared Key.")
        return shared_key
    finally:
        driver.quit()

