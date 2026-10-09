#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import gpsoauth

from Auth.aas_token_retrieval import get_aas_token
from Auth.token_cache import get_cached_value


def get_android_id(*, provisioning_fallback: bool = False):
    credentials = get_cached_value("fcm_credentials")
    try:
        return credentials["gcm"]["android_id"]
    except (KeyError, TypeError):
        if not provisioning_fallback:
            raise RuntimeError(
                "cached fcm_credentials.gcm.android_id is required; run provision first"
            )
        from Auth.fcm_receiver import FcmReceiver

        return FcmReceiver().get_android_id()


def request_token(username, scope, play_services = False):

    aas_token = get_aas_token()
    android_id = get_android_id()
    request_app = 'com.google.android.gms' if play_services else 'com.google.android.apps.adm'

    auth_response = gpsoauth.perform_oauth(
        username, aas_token, android_id,
        service='oauth2:https://www.googleapis.com/auth/' + scope,
        app=request_app,
        client_sig='38918a453d07199354f8b19af05ec6562ced5788')
    token = auth_response.get('Auth')
    if not token:
        raise RuntimeError("Google OAuth token request failed; run provision again")

    return token