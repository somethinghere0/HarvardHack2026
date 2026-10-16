from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nessie_customer_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


@contextmanager
def connect(path: str):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db(path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with connect(path) as c:
        c.executescript(SCHEMA)


def get_user(path: str, username: str):
    with connect(path) as c:
        return c.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def create_user(path: str, username: str, password_hash: str, customer_id: str) -> int:
    """Raises sqlite3.IntegrityError if the username is taken."""
    with connect(path) as c:
        cur = c.execute(
            "INSERT INTO users (username, password_hash, nessie_customer_id, created_at) VALUES (?, ?, ?, ?)",
            (username, password_hash, customer_id, _now().isoformat()),
        )
        return cur.lastrowid


def create_session(path: str, user_id: int, token_hash: str, ttl_hours: int) -> datetime:
    expires = _now() + timedelta(hours=ttl_hours)
    with connect(path) as c:
        c.execute("DELETE FROM sessions WHERE expires_at < ?", (_now().isoformat(),))
        c.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, user_id, expires.isoformat()),
        )
    return expires


def get_session_user(path: str, token_hash: str):
    with connect(path) as c:
        return c.execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > ?",
            (token_hash, _now().isoformat()),
        ).fetchone()


def delete_session(path: str, token_hash: str) -> None:
    with connect(path) as c:
        c.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
