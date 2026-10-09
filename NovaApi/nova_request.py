#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import binascii
import requests

from Auth.adm_token_retrieval import get_adm_token
from Auth.username_provider import get_username

class NovaRequestError(RuntimeError):
    """Safe failure from the Google Nova endpoint."""




def nova_request(api_scope, hex_payload):
    url = "https://android.googleapis.com/nova/" + api_scope

    android_device_manager_oauth_token = get_adm_token(get_username())

    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Authorization": "Bearer " + android_device_manager_oauth_token,
        "Accept-Language": "en-US",
        "User-Agent": "fmd/20006320; gzip",
        "X-Android-Package": "com.google.android.apps.adm",
        "X-Android-Cert": "38918A453D07199354F8B19AF05EC6562CED5788",
    }

    payload = binascii.unhexlify(hex_payload)

    try:
        response = requests.post(url, headers=headers, data=payload, timeout=30)
    except requests.RequestException as exc:
        raise NovaRequestError(f"Nova request failed: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise NovaRequestError(f"Nova request returned HTTP {response.status_code}")
    return response.content.hex()
