#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

from Auth.token_retrieval import request_token

def get_spot_token(username):
    return request_token(username, "spot", True)