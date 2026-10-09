#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

from ProtoDecoders import DeviceUpdate_pb2



def parse_device_update_protobuf(hex_string):
    device_update = DeviceUpdate_pb2.DeviceUpdate()
    device_update.ParseFromString(bytes.fromhex(hex_string))
    return device_update


def parse_device_list_protobuf(hex_string):
    device_list = DeviceUpdate_pb2.DevicesList()
    device_list.ParseFromString(bytes.fromhex(hex_string))
    return device_list


def get_canonic_ids(device_list):
    result = []
    for device in device_list.deviceMetadata:
        if device.identifierInformation.type == DeviceUpdate_pb2.IDENTIFIER_ANDROID: 
            canonic_ids = device.identifierInformation.phoneInformation.canonicIds.canonicId
        else:
            canonic_ids = device.identifierInformation.canonicIds.canonicId
        device_name = device.userDefinedDeviceName
        for canonic_id in canonic_ids:
            result.append((device_name, canonic_id.id))
    return result

