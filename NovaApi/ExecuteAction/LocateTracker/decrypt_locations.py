#
#  GoogleFindMyTools - A set of tools to interact with the Google Find My API
#  Copyright © 2024 Leon Böttger. All rights reserved.
#

import hashlib

from FMDNCrypto.foreign_tracker_cryptor import decrypt
from KeyBackup.cloud_key_decryptor import decrypt_eik, decrypt_aes_gcm
from ProtoDecoders import DeviceUpdate_pb2
from ProtoDecoders import Common_pb2
from ProtoDecoders.DeviceUpdate_pb2 import DeviceRegistration
from SpotApi.GetEidInfoForE2eeDevices.get_eid_info_request import get_eid_info
from SpotApi.GetEidInfoForE2eeDevices.get_owner_key import get_owner_key
from SpotApi.util import MCU_FAST_PAIR_MODEL_ID, flip_bits


def is_mcu_tracker(device_registration: DeviceRegistration) -> bool:
    return device_registration.fastPairModelId == MCU_FAST_PAIR_MODEL_ID


class IdentityKeyDecryptionError(RuntimeError):
    """Raised when a tracker's identity key cannot be decrypted."""


def retrieve_identity_key(device_registration: DeviceRegistration) -> bytes:
    is_mcu = is_mcu_tracker(device_registration)
    encrypted_user_secrets = device_registration.encryptedUserSecrets

    encrypted_identity_key = flip_bits(
        encrypted_user_secrets.encryptedIdentityKey,
        is_mcu)
    owner_key = get_owner_key()

    try:
        return decrypt_eik(owner_key, encrypted_identity_key)
    except Exception as decrypt_error:
        try:
            e2ee_data = get_eid_info()
            current_version = (
                e2ee_data.encryptedOwnerKeyAndMetadata.ownerKeyVersion
            )
        except Exception as metadata_error:
            raise IdentityKeyDecryptionError(
                "Failed to decrypt tracker identity key and verify owner key version"
            ) from metadata_error

        tracker_version = encrypted_user_secrets.ownerKeyVersion
        if tracker_version < current_version:
            raise IdentityKeyDecryptionError(
                "Tracker identity key uses obsolete owner key version "
                f"{tracker_version}; current version is {current_version}"
            ) from decrypt_error
        raise IdentityKeyDecryptionError(
            "Failed to decrypt tracker identity key with owner key version "
            f"{tracker_version}"
        ) from decrypt_error


def extract_locations(device_update_protobuf):
    device_registration = device_update_protobuf.deviceMetadata.information.deviceRegistration
    identity_key = retrieve_identity_key(device_registration)
    locations_proto = device_update_protobuf.deviceMetadata.information.locationInformation.reports.recentLocationAndNetworkLocations
    is_mcu = is_mcu_tracker(device_registration)

    recent_location = locations_proto.recentLocation
    recent_location_time = locations_proto.recentLocationTimestamp

    network_locations = list(locations_proto.networkLocations)
    network_locations_time = list(locations_proto.networkLocationTimestamps)

    if locations_proto.HasField("recentLocation"):
        network_locations.append(recent_location)
        network_locations_time.append(recent_location_time)

    locations = []
    for loc, time in zip(network_locations, network_locations_time):
        if loc.status == Common_pb2.Status.SEMANTIC:
            locations.append({
                "time": int(time.seconds),
                "status": int(loc.status),
                "semantic_name": loc.semanticLocation.locationName
            })
        else:
            encrypted_location = loc.geoLocation.encryptedReport.encryptedLocation
            public_key_random = loc.geoLocation.encryptedReport.publicKeyRandom
            if public_key_random == b"":
                identity_key_hash = hashlib.sha256(identity_key).digest()
                decrypted_location = decrypt_aes_gcm(identity_key_hash, encrypted_location)
            else:
                time_offset = 0 if is_mcu else loc.geoLocation.deviceTimeOffset
                decrypted_location = decrypt(identity_key, encrypted_location, public_key_random, time_offset)
            proto_loc = DeviceUpdate_pb2.Location()
            proto_loc.ParseFromString(decrypted_location)
            locations.append({
                "latitude": proto_loc.latitude / 1e7,
                "longitude": proto_loc.longitude / 1e7,
                "altitude": proto_loc.altitude,
                "time": int(time.seconds),
                "accuracy": loc.geoLocation.accuracy,
                "status": int(loc.status),
                "is_own_report": loc.geoLocation.encryptedReport.isOwnReport
            })
    return locations
