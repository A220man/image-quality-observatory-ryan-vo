"""SQLite persistence: connection handling, schema and transactional helpers."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    format TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    batch TEXT NOT NULL DEFAULT 'default',
    blur_score REAL NOT NULL,
    edge_density REAL NOT NULL,
    mean_luma REAL NOT NULL,
    shadow_clip REAL NOT NULL,
    highlight_clip REAL NOT NULL,
    rms_contrast REAL NOT NULL,
    dynamic_range REAL NOT NULL,
    failures TEXT NOT NULL,
    decision TEXT NOT NULL,
    quality_score REAL NOT NULL,
    label TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_images_decision ON images(decision);
CREATE INDEX IF NOT EXISTS idx_images_batch ON images(batch);
CREATE UNIQUE INDEX IF NOT EXISTS idx_images_sha_batch ON images(sha256, batch);

CREATE TABLE IF NOT EXISTS policy (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    blur_min REAL NOT NULL,
    luma_min REAL NOT NULL,
    luma_max REAL NOT NULL,
    clip_max REAL NOT NULL,
    contrast_min REAL NOT NULL,
    review_margin REAL NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    username TEXT NOT NULL,
    roles TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_states (
    state TEXT PRIMARY KEY,
    nonce TEXT NOT NULL,
    code_verifier TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Thread-safe wrapper around a single SQLite connection.

    SQLite serialises writers anyway; a process-level lock keeps transactions
    from interleaving across FastAPI worker threads.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def query(self, sql: str, params: tuple | list = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple | list = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
