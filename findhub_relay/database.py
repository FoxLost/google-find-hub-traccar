#
# GoogleFindMyTools - A set of tools to interact with the Google Find My API
# Copyright © 2024 Leon Böttger. All rights reserved.
#
"""Transactional SQLite persistence for relay state and outbound positions."""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Iterator

SCHEMA_VERSION = 1


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            try:
                descriptor = os.open(
                    self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                )
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
            os.chmod(self.path, 0o600)
        with self.connect() as db, db:
            db.execute("PRAGMA journal_mode = WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    last_seen_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS relay_health (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    daemon_status TEXT NOT NULL,
                    cycle_status TEXT,
                    started_at INTEGER,
                    cycle_started_at INTEGER,
                    cycle_finished_at INTEGER,
                    last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS fcm_credentials (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    credentials_json TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbound_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    accuracy REAL,
                    altitude REAL,
                    valid INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    sent_at INTEGER,
                    UNIQUE(device_id, timestamp)
                );
                CREATE INDEX IF NOT EXISTS outbound_unsent
                    ON outbound_positions(sent_at, id);
                """
            )
            row = db.execute("SELECT version FROM schema_meta").fetchone()
            if row is None:
                db.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
            elif row["version"] != SCHEMA_VERSION:
                raise RuntimeError(
                    f"unsupported database schema {row['version']}; expected {SCHEMA_VERSION}"
                )
            db.execute(
                """INSERT OR IGNORE INTO relay_health(singleton, daemon_status)
                   VALUES (1, 'stopped')"""
            )

    def replace_devices(self, devices: list[tuple[str, str]]) -> None:
        now = int(time.time())
        with self.connect() as db, db:
            # The Find Hub response is an authoritative snapshot. Delete and
            # rebuild inside one transaction so readers see either generation.
            db.execute("DELETE FROM devices")
            db.executemany(
                "INSERT INTO devices(device_id, name, last_seen_at) VALUES (?, ?, ?)",
                ((device_id, name, now) for name, device_id in devices),
            )

    def list_devices(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT device_id, name, last_seen_at FROM devices ORDER BY name, device_id"
            )]

    def save_fcm_credentials(self, credentials: dict) -> None:
        encoded = json.dumps(credentials, separators=(",", ":"), sort_keys=True)
        with self.connect() as db, db:
            db.execute(
                """INSERT INTO fcm_credentials(singleton, credentials_json, updated_at)
                   VALUES (1, ?, ?) ON CONFLICT(singleton) DO UPDATE SET
                   credentials_json=excluded.credentials_json,
                   updated_at=excluded.updated_at""",
                (encoded, int(time.time())),
            )

    def load_fcm_credentials(self) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT credentials_json FROM fcm_credentials WHERE singleton=1"
            ).fetchone()
        return json.loads(row["credentials_json"]) if row else None

    def enqueue_positions(self, device_id: str, locations: list[dict]) -> int:
        now = int(time.time())
        inserted = 0
        with self.connect() as db, db:
            for location in sorted(locations, key=lambda item: int(item["time"])):
                before = db.total_changes
                db.execute(
                    """INSERT OR IGNORE INTO outbound_positions(
                         device_id, timestamp, latitude, longitude, accuracy, altitude,
                         valid, source, report_type, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        device_id,
                        int(location["time"]),
                        float(location["latitude"]),
                        float(location["longitude"]),
                        location.get("accuracy"),
                        location.get("altitude"),
                        1,
                        "findhub",
                        "own" if location.get("is_own_report") else "network",
                        now,
                    ),
                )
                inserted += db.total_changes - before
        return inserted

    def pending_positions(self, limit: int = 1000) -> list[dict]:
        if limit <= 0:
            raise ValueError("pending position limit must be greater than zero")
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                """SELECT id, device_id, timestamp, latitude, longitude, accuracy,
                          altitude, valid, source, report_type
                   FROM outbound_positions WHERE sent_at IS NULL
                   ORDER BY timestamp, id LIMIT ?""",
                (limit,),
            )]

    def pending_position_count(self) -> int:
        with self.connect() as db:
            return db.execute(
                "SELECT COUNT(*) FROM outbound_positions WHERE sent_at IS NULL"
            ).fetchone()[0]

    def mark_sent(self, position_id: int) -> None:
        with self.connect() as db, db:
            db.execute(
                "UPDATE outbound_positions SET sent_at=? WHERE id=? AND sent_at IS NULL",
                (int(time.time()), position_id),
            )

    def set_health(self, **fields: object) -> None:
        allowed = {
            "daemon_status", "cycle_status", "started_at", "cycle_started_at",
            "cycle_finished_at", "last_error",
        }
        invalid = fields.keys() - allowed
        if invalid:
            raise ValueError(f"invalid health fields: {sorted(invalid)}")
        if not fields:
            return
        assignments = ", ".join(f"{name}=?" for name in fields)
        with self.connect() as db, db:
            db.execute(
                f"UPDATE relay_health SET {assignments} WHERE singleton=1",  # names allowlisted
                tuple(fields.values()),
            )

    def health(self, poll_interval_seconds: int) -> dict:
        with self.connect() as db:
            version = db.execute("SELECT version FROM schema_meta").fetchone()["version"]
            row = db.execute("SELECT * FROM relay_health WHERE singleton=1").fetchone()
            pending = db.execute(
                "SELECT COUNT(*) AS count FROM outbound_positions WHERE sent_at IS NULL"
            ).fetchone()["count"]
        result = dict(row)
        result.update(schema_version=version, pending_positions=pending)
        finished_at = result["cycle_finished_at"]
        result["stale"] = (
            finished_at is None
            or int(time.time()) - finished_at > poll_interval_seconds * 2
        )
        result["healthy"] = bool(
            version == SCHEMA_VERSION
            and result["daemon_status"] == "running"
            and result["cycle_status"] == "ok"
            and not result["stale"]
        )
        return result
