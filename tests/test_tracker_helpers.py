# Copyright © 2024 Leon Böttger. All rights reserved.
import unittest

from NovaApi.ExecuteAction.LocateTracker.decrypt_locations import is_mcu_tracker
from ProtoDecoders.DeviceUpdate_pb2 import DeviceRegistration
from SpotApi.util import MCU_FAST_PAIR_MODEL_ID, flip_bits


class TrackerHelperTests(unittest.TestCase):
    def test_flip_bits_is_conditional(self):
        data = bytes((0x00, 0x55, 0xFF))
        self.assertEqual(flip_bits(data, True), bytes((0xFF, 0xAA, 0x00)))
        self.assertIs(flip_bits(data, False), data)

    def test_mcu_tracker_uses_fast_pair_model_id(self):
        registration = DeviceRegistration(fastPairModelId=MCU_FAST_PAIR_MODEL_ID)
        self.assertTrue(is_mcu_tracker(registration))
        registration.fastPairModelId = "other"
        self.assertFalse(is_mcu_tracker(registration))


if __name__ == "__main__":
    unittest.main()
