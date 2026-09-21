import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_ip TEXT,
    app_version TEXT
);

CREATE TABLE IF NOT EXISTS clipboard_items (
    id TEXT PRIMARY KEY,
    source_device TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_clipboard_created ON clipboard_items(created_at DESC);

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    original_name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    source_device TEXT,
    target_device TEXT,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    mime_type TEXT,
    extension TEXT,
    category TEXT,
    subcategory TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT,
    extracted_text TEXT,
    status TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    duplicate_of TEXT,
    created_at TEXT NOT NULL,
    organized_at TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_sha ON files(sha256);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_created ON files(created_at DESC);

CREATE TABLE IF NOT EXISTS file_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    from_path TEXT,
    to_path TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(file_id) REFERENCES files(id)
);

CREATE TABLE IF NOT EXISTS transfers (
    id TEXT PRIMARY KEY,
    source_device TEXT NOT NULL,
    target_device TEXT,
    filename TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    downloaded_at TEXT
);

CREATE TABLE IF NOT EXISTS backup_snapshots (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    root_name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    total_files INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS backup_entries (
    snapshot_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    PRIMARY KEY(snapshot_id, relative_path),
    FOREIGN KEY(snapshot_id) REFERENCES backup_snapshots(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_backup_sha ON backup_entries(sha256);

CREATE TABLE IF NOT EXISTS blobs (
    sha256 TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def fetch_one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(query, params).fetchone()
            return dict(row) if row else None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        with self.connect() as connection:
            connection.execute(query, params)
            connection.commit()

    @staticmethod
    def decode_file(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["tags"] = json.loads(result.pop("tags_json", "[]") or "[]")
        result.pop("extracted_text", None)
        return result

