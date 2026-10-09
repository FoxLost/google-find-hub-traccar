#
# GoogleFindMyTools - A set of tools to interact with the Google Find My API
# Copyright © 2024 Leon Böttger. All rights reserved.
#
"""Command line entrypoints for the relay appliance."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import signal
import sys

from . import __version__
from .config import Config, ConfigError
from .database import Database


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m findhub_relay")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "command", choices=("provision", "devices", "once", "daemon", "healthcheck")
    )
    return parser


def _validate_credentials(config: Config) -> None:
    if not config.credentials_file.is_file():
        raise RuntimeError(
            f"credentials file not found at {config.credentials_file}; run provision first"
        )
    try:
        with config.credentials_file.open("r", encoding="utf-8") as handle:
            credentials = json.load(handle)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"credentials file at {config.credentials_file} is not valid JSON"
        ) from exc
    if not isinstance(credentials, dict):
        raise RuntimeError(
            f"credentials file at {config.credentials_file} must contain a JSON object"
        )
    missing = [
        key
        for key in ("aas_token", "username", "owner_key", "fcm_credentials")
        if not credentials.get(key)
    ]
    fcm_credentials = credentials.get("fcm_credentials")
    try:
        if not fcm_credentials["gcm"]["android_id"]:
            missing.append("fcm_credentials.gcm.android_id")
        if not fcm_credentials["fcm"]["registration"]["token"]:
            missing.append("fcm_credentials.fcm.registration.token")
    except (KeyError, TypeError):
        missing.append("complete fcm_credentials")
    if missing:
        raise RuntimeError(
            f"credentials file is missing required entries: {', '.join(dict.fromkeys(missing))}; "
            "run provision first"
        )



def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _components(config: Config, database: Database):
    from .fcm import PersistentFcm
    from .findhub import FindHubClient
    from .osmand import OsmandSender
    from .service import RelayService

    fcm = PersistentFcm(database)
    findhub = FindHubClient(fcm, config.location_timeout_seconds)
    sender = OsmandSender(database, config.traccar_url, config.location_timeout_seconds)
    return fcm, findhub, RelayService(config, database, findhub, sender)


async def _run(command: str, config: Config, database: Database) -> int:
    if command == "provision":
        from Auth.aas_token_retrieval import get_aas_token
        from .fcm import PersistentFcm
        from .findhub import FindHubClient
        from SpotApi.GetEidInfoForE2eeDevices.get_owner_key import get_owner_key

        await asyncio.to_thread(get_aas_token)
        fcm = PersistentFcm(database)
        findhub = FindHubClient(fcm, config.location_timeout_seconds)
        try:
            devices = await findhub.list_devices()
            if not devices:
                raise RuntimeError("provisioning found no Find Hub devices")
            selected_id = config.device_ids[0] if config.device_ids else devices[0][1]
            available = {device_id for _, device_id in devices}
            if selected_id not in available:
                raise RuntimeError(
                    f"configured provisioning device {selected_id} was not found"
                )
            await findhub.locate(selected_id)
            # Complete end-to-end key provisioning even if this response has no
            # coordinate report requiring the owner key.
            await asyncio.to_thread(get_owner_key)
        finally:
            await fcm.stop()
        _validate_credentials(config)
        print("Credentials provisioned successfully")
        return 0

    if command == "healthcheck":
        health = database.health(config.poll_interval_seconds)
        print(json.dumps(health, sort_keys=True))
        return 0 if health["healthy"] else 1

    fcm, findhub, service = _components(config, database)
    try:
        if command == "devices":
            devices = await findhub.list_devices()
            database.replace_devices(devices)
            print(json.dumps(
                [{"name": name, "device_id": device_id} for name, device_id in devices],
                indent=2,
            ))
            return 0
        if command == "once":
            result = await service.run_cycle(force_refresh=True)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["status"] == "ok" else 1
        if command == "daemon":
            stop_event = asyncio.Event()
            loop = asyncio.get_running_loop()
            for signum in (signal.SIGTERM, signal.SIGINT):
                try:
                    loop.add_signal_handler(signum, stop_event.set)
                except NotImplementedError:  # Windows event loops
                    signal.signal(signum, lambda *_: loop.call_soon_threadsafe(stop_event.set))
            await service.run_daemon(stop_event)
            return 0
        raise AssertionError(command)
    finally:
        await fcm.stop()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = Config.from_env(require_traccar=args.command in {"once", "daemon"})
        _configure_logging(config.log_level)
        # Existing auth modules read this variable dynamically.
        os.environ["CREDENTIALS_FILE"] = str(config.credentials_file)
        if args.command in {"devices", "once", "daemon"}:
            _validate_credentials(config)
        database = Database(config.database_path)
        database.initialize()
        return asyncio.run(_run(args.command, config, database))
    except (ConfigError, OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        print(f"fatal: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
