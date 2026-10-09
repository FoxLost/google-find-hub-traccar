#
# GoogleFindMyTools - A set of tools to interact with the Google Find My API
# Copyright © 2024 Leon Böttger. All rights reserved.
#
"""Environment configuration for the relay."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


class ConfigError(ValueError):
    """Raised for invalid relay configuration."""


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class Config:
    traccar_url: str | None
    poll_interval_seconds: int
    location_timeout_seconds: int
    device_refresh_interval_seconds: int
    device_ids: tuple[str, ...] | None
    data_directory: Path
    credentials_file: Path
    log_level: str

    @property
    def database_path(self) -> Path:
        return self.data_directory / "relay.db"

    @classmethod
    def from_env(cls, *, require_traccar: bool = False) -> "Config":
        data_directory = Path(os.environ.get("DATA_DIRECTORY", "/data")).expanduser()
        credentials = Path(
            os.environ.get("CREDENTIALS_FILE", str(data_directory / "credentials.json"))
        ).expanduser()
        raw_ids = os.environ.get("DEVICE_IDS", "").strip()
        device_ids = tuple(dict.fromkeys(x.strip() for x in raw_ids.split(",") if x.strip())) or None
        traccar_url = os.environ.get("TRACCAR_URL", "").strip() or None
        if require_traccar and not traccar_url:
            raise ConfigError("TRACCAR_URL is required for once and daemon")
        level = os.environ.get("LOG_LEVEL", "INFO").upper()
        if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ConfigError(f"LOG_LEVEL has unsupported value {level!r}")
        return cls(
            traccar_url=traccar_url,
            poll_interval_seconds=_positive_int("POLL_INTERVAL_SECONDS", 900),
            location_timeout_seconds=_positive_int("LOCATION_TIMEOUT_SECONDS", 30),
            device_refresh_interval_seconds=_positive_int(
                "DEVICE_REFRESH_INTERVAL_SECONDS", 3600
            ),
            device_ids=device_ids,
            data_directory=data_directory,
            credentials_file=credentials,
            log_level=level,
        )
