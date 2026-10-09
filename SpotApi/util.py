#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

MCU_FAST_PAIR_MODEL_ID = "003200"


def flip_bits(data: bytes, enabled: bool) -> bytes:
    """Flip every bit when decoding custom microcontroller tracker keys."""
    if enabled:
        return bytes(byte ^ 0xFF for byte in data)
    return data
