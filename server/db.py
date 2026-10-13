"""SQLite layer: connections, schema, migrations, append-only audit triggers (D8)."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .settings import CONFIG

_local = threading.local()
_init_lock = threading.Lock()
_initialized = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    tags          TEXT NOT NULL DEFAULT '[]',
    file_path     TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    endpoints     TEXT NOT NULL DEFAULT '[]',
    cipher        TEXT,
    tls_version_min TEXT,
    has_auth_user_pass INTEGER NOT NULL DEFAULT 0,
    cert_expires_at TEXT,
    parse_error   TEXT,
    status        TEXT NOT NULL DEFAULT 'Valid',
    enabled       INTEGER NOT NULL DEFAULT 1,
    config_sha256 TEXT NOT NULL,
    previous_text TEXT,
    previous_name TEXT,
    updated_at    TEXT NOT NULL
);

-- Username and password for profiles that sign in (owner decision: stored plain like the
-- .ovpn files). Only ever written to the server's root-only <name>.auth file on enable.
CREATE TABLE IF NOT EXISTS profile_auth (
    profile_id TEXT PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
    username   TEXT NOT NULL,
    password   TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS share_links (
    token      TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    one_time   INTEGER NOT NULL DEFAULT 0,
    used_count INTEGER NOT NULL DEFAULT 0,
    revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS policy_versions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    note       TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    action          TEXT NOT NULL,
    section         TEXT NOT NULL,
    target          TEXT NOT NULL DEFAULT '',
    outcome         TEXT NOT NULL DEFAULT 'ok',
    detail          TEXT NOT NULL DEFAULT '{}',
    undoes_event_id INTEGER
);

-- Principle III / FR-050: history cannot be rewritten, not even by a bug.
CREATE TRIGGER IF NOT EXISTS audit_no_update
    BEFORE UPDATE ON audit
BEGIN
    SELECT RAISE(ABORT, 'audit log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS audit_no_delete
    BEFORE DELETE ON audit
BEGIN
    SELECT RAISE(ABORT, 'audit log is append-only');
END;

CREATE INDEX IF NOT EXISTS audit_ts_idx ON audit(ts DESC);
CREATE INDEX IF NOT EXISTS audit_action_idx ON audit(action);
CREATE INDEX IF NOT EXISTS profiles_status_idx ON profiles(status);
"""


def get_conn() -> sqlite3.Connection:
    """Thread-local connection (FastAPI sync endpoints run in a threadpool)."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        Path(CONFIG.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(CONFIG.db_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        _local.conn = conn
    return conn


def init_db() -> None:
    global _initialized
    with _init_lock:
        if _initialized:
            return
        with get_conn() as c:
            c.executescript(SCHEMA)
        _initialized = True


def get_setting(key: str, default: str | None = None) -> str | None:
    row = get_conn().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_conn() as c:
        c.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def delete_setting(key: str) -> None:
    with get_conn() as c:
        c.execute("DELETE FROM settings WHERE key=?", (key,))
