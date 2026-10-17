"""SQLite store for the orchestrator: engagements, personas, the event timeline, OTP challenges,
and the email log. One file, no ORM — plenty for a demo."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS engagements (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'new',          -- new|baited|active|drained|closed
    channel TEXT NOT NULL DEFAULT 'email',
    scammer_email TEXT,
    subject TEXT,
    risk_score INTEGER NOT NULL DEFAULT 0,
    tags TEXT NOT NULL DEFAULT '[]',             -- JSON array of indicator tags
    summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS personas (
    id TEXT PRIMARY KEY,
    engagement_id TEXT REFERENCES engagements(id) ON DELETE CASCADE,
    username TEXT NOT NULL,
    password TEXT NOT NULL,                       -- decoy credential, handed to the scammer's portal
    email TEXT NOT NULL,                          -- inbox+persona_<id>@...
    customer_id TEXT,
    first_name TEXT,
    last_name TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id TEXT REFERENCES engagements(id) ON DELETE CASCADE,
    source TEXT NOT NULL,                          -- gmail|proxy|nessie|agent|system
    type TEXT NOT NULL,
    data TEXT NOT NULL DEFAULT '{}',              -- JSON blob
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS otps (
    challenge_id TEXT PRIMARY KEY,
    persona_id TEXT REFERENCES personas(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id TEXT REFERENCES engagements(id) ON DELETE CASCADE,
    direction TEXT NOT NULL,                       -- in|out
    kind TEXT NOT NULL DEFAULT 'other',           -- scam|otp|reply|other
    sender TEXT,
    recipient TEXT,
    subject TEXT,
    body TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_eng ON events(engagement_id, id);
CREATE INDEX IF NOT EXISTS ix_personas_eng ON personas(engagement_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _row(r) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("tags", "data"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except (ValueError, TypeError):
                pass
    return d


# ---- engagements ----------------------------------------------------------

def create_engagement(path: str, eid: str, channel: str, scammer_email: str | None, subject: str | None) -> dict:
    ts = now()
    with connect(path) as c:
        c.execute(
            "INSERT INTO engagements (id, channel, scammer_email, subject, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (eid, channel, scammer_email, subject, ts, ts),
        )
    return get_engagement(path, eid)


def get_engagement(path: str, eid: str) -> dict | None:
    with connect(path) as c:
        return _row(c.execute("SELECT * FROM engagements WHERE id = ?", (eid,)).fetchone())


def list_engagements(path: str) -> list[dict]:
    with connect(path) as c:
        return [_row(r) for r in c.execute("SELECT * FROM engagements ORDER BY updated_at DESC").fetchall()]


def update_engagement(path: str, eid: str, **fields) -> None:
    if not fields:
        return
    fields = {k: (json.dumps(v) if k == "tags" else v) for k, v in fields.items()}
    fields["updated_at"] = now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect(path) as c:
        c.execute(f"UPDATE engagements SET {cols} WHERE id = ?", (*fields.values(), eid))


# ---- personas -------------------------------------------------------------

def create_persona(path: str, p: dict) -> None:
    with connect(path) as c:
        c.execute(
            "INSERT INTO personas (id, engagement_id, username, password, email, customer_id, "
            "first_name, last_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (p["id"], p["engagement_id"], p["username"], p["password"], p["email"], p.get("customer_id"),
             p.get("first_name"), p.get("last_name"), now()),
        )


def get_persona(path: str, pid: str) -> dict | None:
    with connect(path) as c:
        return _row(c.execute("SELECT * FROM personas WHERE id = ?", (pid,)).fetchone())


def get_persona_by_username(path: str, username: str) -> dict | None:
    with connect(path) as c:
        return _row(c.execute("SELECT * FROM personas WHERE username = ?", (username.lower(),)).fetchone())


def set_persona_customer(path: str, pid: str, customer_id: str) -> None:
    with connect(path) as c:
        c.execute("UPDATE personas SET customer_id = ? WHERE id = ?", (customer_id, pid))


def find_engagement_by_account(path: str, account_id: str) -> str | None:
    """Accounts are recorded in each persona.created event; map one back to its engagement."""
    with connect(path) as c:
        rows = c.execute(
            "SELECT engagement_id, data FROM events WHERE type = 'persona.created'").fetchall()
    for r in rows:
        try:
            if account_id in (json.loads(r["data"]).get("accounts") or []):
                return r["engagement_id"]
        except (ValueError, TypeError):
            continue
    return None


# ---- events ---------------------------------------------------------------

def add_event(path: str, eid: str | None, source: str, type_: str, data: dict | None = None) -> dict:
    with connect(path) as c:
        cur = c.execute(
            "INSERT INTO events (engagement_id, source, type, data, created_at) VALUES (?, ?, ?, ?, ?)",
            (eid, source, type_, json.dumps(data or {}), now()),
        )
        return _row(c.execute("SELECT * FROM events WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_events(path: str, eid: str) -> list[dict]:
    with connect(path) as c:
        return [_row(r) for r in c.execute(
            "SELECT * FROM events WHERE engagement_id = ? ORDER BY id", (eid,)).fetchall()]


def list_transfer_events(path: str, eid: str) -> list[dict]:
    """Money-movement events used by the indicator engine."""
    with connect(path) as c:
        rows = c.execute(
            "SELECT * FROM events WHERE engagement_id = ? AND type IN "
            "('transfer.created','transaction.completed','withdrawal.created') ORDER BY id", (eid,)).fetchall()
    return [_row(r) for r in rows]


# ---- otps -----------------------------------------------------------------

def create_otp(path: str, challenge_id: str, persona_id: str, code: str, expires_at: str) -> None:
    with connect(path) as c:
        c.execute(
            "INSERT INTO otps (challenge_id, persona_id, code, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (challenge_id, persona_id, code, expires_at, now()),
        )


def get_otp(path: str, challenge_id: str) -> dict | None:
    with connect(path) as c:
        return _row(c.execute("SELECT * FROM otps WHERE challenge_id = ?", (challenge_id,)).fetchone())


def latest_otp_for_persona(path: str, persona_id: str) -> dict | None:
    with connect(path) as c:
        return _row(c.execute(
            "SELECT * FROM otps WHERE persona_id = ? AND consumed = 0 ORDER BY created_at DESC LIMIT 1",
            (persona_id,)).fetchone())


def consume_otp(path: str, challenge_id: str) -> None:
    with connect(path) as c:
        c.execute("UPDATE otps SET consumed = 1 WHERE challenge_id = ?", (challenge_id,))


# ---- emails ---------------------------------------------------------------

def add_email(path: str, eid: str | None, direction: str, kind: str, sender: str | None,
              recipient: str | None, subject: str | None, body: str | None) -> None:
    with connect(path) as c:
        c.execute(
            "INSERT INTO emails (engagement_id, direction, kind, sender, recipient, subject, body, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, direction, kind, sender, recipient, subject, body, now()),
        )


def list_emails(path: str, eid: str) -> list[dict]:
    with connect(path) as c:
        return [_row(r) for r in c.execute(
            "SELECT * FROM emails WHERE engagement_id = ? ORDER BY id", (eid,)).fetchall()]
