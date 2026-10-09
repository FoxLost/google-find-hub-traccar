#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import gpsoauth
import os

from Auth.token_cache import get_cached_value_or_set, set_cached_value
from Auth.username_provider import get_username, username_string


def _provisioning_username() -> str:
    username = os.environ.get("GOOGLE_USERNAME", "").strip() or get_username().strip()
    if not username:
        username = input("Google account email: ").strip()
    if not username:
        raise RuntimeError("Google account email must not be empty")
    set_cached_value(username_string, username)
    return username


def _generate_aas_token():
    # Browser and legacy FCM imports are provisioning-only. Runtime consumers
    # use the cached account token and never import Selenium/Chrome.
    from Auth.auth_flow import request_oauth_account_token_flow
    from Auth.fcm_receiver import FcmReceiver
    username = _provisioning_username()
    android_id = FcmReceiver().get_android_id()
    token = request_oauth_account_token_flow()

    aas_token_response = gpsoauth.exchange_token(username, token, android_id)
    aas_token = aas_token_response.get('Token')
    if not aas_token:
        raise RuntimeError("Google account token exchange failed")

    if 'Email' in aas_token_response:
        email = aas_token_response['Email']
        set_cached_value(username_string, email)

    return aas_token


def get_aas_token():
    return get_cached_value_or_set('aas_token', _generate_aas_token)
