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
    password TEXT NOT NULL,                       -- decoy credential the phished login uses
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
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_id TEXT UNIQUE,                          -- source message id, so we vet each email once
    sender TEXT,
    subject TEXT,
    body TEXT,
    verdict TEXT NOT NULL DEFAULT 'pending',       -- pending (detonating)|safe|scam|error
    vector TEXT,
    confidence REAL,
    reason TEXT,
    action TEXT,                                   -- held|delivered|quarantined|review
    engagement_id TEXT,                            -- the sandbox detonation run for this email
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engagement_id TEXT REFERENCES engagements(id) ON DELETE CASCADE,
    step INTEGER NOT NULL DEFAULT 0,
    label TEXT,
    image TEXT NOT NULL,                           -- data: URL (jpeg base64) of the agent's browser
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS swarm_runs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'running',       -- running|finished|stopped|error
    scenarios TEXT NOT NULL DEFAULT '[]',         -- JSON array of scam types requested
    customers INTEGER NOT NULL DEFAULT 0,
    anomaly_rate REAL NOT NULL DEFAULT 0,
    totals TEXT NOT NULL DEFAULT '{}',            -- JSON rollup (cases, caught, missed, fp, calls)
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS swarm_cases (
    id TEXT PRIMARY KEY,
    run_id TEXT REFERENCES swarm_runs(id) ON DELETE CASCADE,
    scenario TEXT,                                -- scam type seeded for this case (or 'clean')
    customer_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued',        -- queued|booting|analyzing|done|error
    runtime TEXT,                                 -- daytona|local
    sandbox_id TEXT,
    n_txns INTEGER DEFAULT 0,
    planted INTEGER DEFAULT 0,                     -- how many anomalies Nessie injected (truth)
    flagged INTEGER DEFAULT 0,                     -- how many our detector flagged
    caught INTEGER DEFAULT 0,                      -- flagged AND anomalous
    missed INTEGER DEFAULT 0,                      -- anomalous but not flagged
    false_pos INTEGER DEFAULT 0,                   -- flagged but not anomalous
    used_claude INTEGER DEFAULT 0,                 -- borderline txns escalated to Claude
    result TEXT,                                   -- JSON detail (per-txn verdicts, timing)
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_cases_run ON swarm_cases(run_id, id);
CREATE TABLE IF NOT EXISTS nessie_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT,                                    -- engagement id, swarm run id, or 'system'
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    status INTEGER,
    ms INTEGER,
    request TEXT,                                  -- JSON body sent (truncated)
    response TEXT,                                 -- JSON body received (truncated)
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_nessie_scope ON nessie_calls(scope, id);
CREATE TABLE IF NOT EXISTS interdictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_id TEXT,
    payer_id TEXT,
    payee_id TEXT,
    amount_cents INTEGER,
    action TEXT NOT NULL,                          -- declined|cancelled|flagged|approved
    reason TEXT,
    engagement_id TEXT,                            -- the engagement whose intel caught it
    source TEXT,                                   -- decision_hook|poller
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_eng ON events(engagement_id, id);
CREATE INDEX IF NOT EXISTS ix_personas_eng ON personas(engagement_id);
CREATE INDEX IF NOT EXISTS ix_shots_eng ON shots(engagement_id, id);
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


# Columns added after the first schema shipped; applied to existing databases on startup.
_MIGRATIONS = [
    ("engagements", "grade", "TEXT"),      # scam confidence: likely | confirmed
    ("engagements", "armed", "INTEGER NOT NULL DEFAULT 0"),
    ("messages", "grade", "TEXT"),
]


def init_db(path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with connect(path) as c:
        c.executescript(SCHEMA)
        for table, col, decl in _MIGRATIONS:
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})").fetchall()}
            if col not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


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


def list_events_of_types(path: str, types: tuple[str, ...]) -> list[dict]:
    """Events of the given types across every engagement (for the watchlist and crew linkage)."""
    marks = ",".join("?" * len(types))
    with connect(path) as c:
        return [_row(r) for r in c.execute(
            f"SELECT * FROM events WHERE type IN ({marks}) ORDER BY id", types).fetchall()]


def has_event(path: str, eid: str, type_: str, **match) -> bool:
    for e in list_events(path, eid):
        if e["type"] == type_ and all(e["data"].get(k) == v for k, v in match.items()):
            return True
    return False


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


# ---- messages (inbox firewall log) ----------------------------------------

def message_seen(path: str, gmail_id: str) -> bool:
    if not gmail_id:
        return False
    with connect(path) as c:
        return c.execute("SELECT 1 FROM messages WHERE gmail_id = ?", (gmail_id,)).fetchone() is not None


def add_message(path: str, m: dict) -> int:
    with connect(path) as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO messages (gmail_id, sender, subject, body, verdict, vector, "
            "confidence, reason, action, engagement_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (m.get("gmail_id"), m.get("sender"), m.get("subject"), m.get("body"), m.get("verdict", "pending"),
             m.get("vector"), m.get("confidence"), m.get("reason"), m.get("action"),
             m.get("engagement_id"), now()),
        )
        return cur.lastrowid


def update_message(path: str, msg_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect(path) as c:
        c.execute(f"UPDATE messages SET {cols} WHERE id = ?", (*fields.values(), msg_id))


def messages_by_gmail_ids(path: str, gmail_ids: list[str]) -> list[dict]:
    if not gmail_ids:
        return []
    marks = ",".join("?" * len(gmail_ids))
    with connect(path) as c:
        return [_row(r) for r in c.execute(
            f"SELECT gmail_id, verdict, vector, reason, action, engagement_id FROM messages WHERE gmail_id IN ({marks})",
            gmail_ids).fetchall()]


def message_for_engagement(path: str, eid: str) -> dict | None:
    with connect(path) as c:
        return _row(c.execute("SELECT * FROM messages WHERE engagement_id = ? ORDER BY id DESC LIMIT 1", (eid,)).fetchone())


def list_messages(path: str, limit: int = 100) -> list[dict]:
    with connect(path) as c:
        rows = c.execute("SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = _row(r)
        if d.get("body"):
            d["body"] = d["body"][:600]  # keep the list payload small
        out.append(d)
    return out


# ---- agent screenshots ----------------------------------------------------

def add_shot(path: str, eid: str, step: int, label: str | None, image: str) -> None:
    with connect(path) as c:
        c.execute("INSERT INTO shots (engagement_id, step, label, image, created_at) VALUES (?, ?, ?, ?, ?)",
                  (eid, step, label, image, now()))


def list_shots(path: str, eid: str) -> list[dict]:
    with connect(path) as c:
        return [_row(r) for r in c.execute(
            "SELECT step, label, image, created_at FROM shots WHERE engagement_id = ? ORDER BY id",
            (eid,)).fetchall()]


def add_nessie_call(path: str, scope: str | None, method: str, url_path: str, status: int | None,
                    ms: int, request: str, response: str) -> None:
    with connect(path) as c:
        c.execute("INSERT INTO nessie_calls (scope, method, path, status, ms, request, response, created_at) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                  (scope, method, url_path, status, ms, request[:4000], response[:8000], now()))


def list_nessie_calls(path: str, scope: str | None = None, after: int = 0, limit: int = 200) -> list[dict]:
    q, args = "SELECT * FROM nessie_calls WHERE id > ?", [after]
    if scope:
        q += " AND scope = ?"
        args.append(scope)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with connect(path) as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def nessie_call_stats(path: str, scope: str | None = None) -> dict:
    q = "SELECT COUNT(*) n, AVG(ms) avg_ms, SUM(status >= 400) errors FROM nessie_calls"
    args = []
    if scope:
        q += " WHERE scope = ?"
        args.append(scope)
    with connect(path) as c:
        r = c.execute(q, args).fetchone()
    return {"calls": r["n"] or 0, "avg_ms": round(r["avg_ms"] or 0), "errors": r["errors"] or 0}


def create_swarm(path: str, rid: str, scenarios: list, customers: int, anomaly_rate: float) -> dict:
    import json
    with connect(path) as c:
        c.execute("INSERT INTO swarm_runs (id, scenarios, customers, anomaly_rate, created_at, updated_at) "
                  "VALUES (?, ?, ?, ?, ?, ?)", (rid, json.dumps(scenarios), customers, anomaly_rate, now(), now()))
    return get_swarm(path, rid)


def update_swarm(path: str, rid: str, **fields) -> None:
    import json
    if not fields:
        return
    sets, args = [], []
    for k, v in fields.items():
        sets.append(f"{k} = ?")
        args.append(json.dumps(v) if k == "totals" else v)
    args += [now(), rid]
    with connect(path) as c:
        c.execute(f"UPDATE swarm_runs SET {', '.join(sets)}, updated_at = ? WHERE id = ?", args)


def get_swarm(path: str, rid: str) -> dict | None:
    import json
    with connect(path) as c:
        r = c.execute("SELECT * FROM swarm_runs WHERE id = ?", (rid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["scenarios"] = json.loads(d.get("scenarios") or "[]")
    d["totals"] = json.loads(d.get("totals") or "{}")
    return d


def list_swarms(path: str, limit: int = 20) -> list[dict]:
    import json
    with connect(path) as c:
        rows = c.execute("SELECT * FROM swarm_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["scenarios"] = json.loads(d.get("scenarios") or "[]")
        d["totals"] = json.loads(d.get("totals") or "{}")
        out.append(d)
    return out


def add_case(path: str, cid: str, rid: str, scenario: str, customer_id: str) -> None:
    with connect(path) as c:
        c.execute("INSERT INTO swarm_cases (id, run_id, scenario, customer_id, created_at, updated_at) "
                  "VALUES (?, ?, ?, ?, ?, ?)", (cid, rid, scenario, customer_id, now(), now()))


def update_case(path: str, cid: str, **fields) -> None:
    import json
    if not fields:
        return
    sets, args = [], []
    for k, v in fields.items():
        sets.append(f"{k} = ?")
        args.append(json.dumps(v) if k == "result" else v)
    args += [now(), cid]
    with connect(path) as c:
        c.execute(f"UPDATE swarm_cases SET {', '.join(sets)}, updated_at = ? WHERE id = ?", args)


def list_cases(path: str, rid: str) -> list[dict]:
    with connect(path) as c:
        return [dict(r) for r in c.execute(
            "SELECT id, run_id, scenario, customer_id, status, runtime, sandbox_id, n_txns, planted, "
            "flagged, caught, missed, false_pos, used_claude, updated_at "
            "FROM swarm_cases WHERE run_id = ? ORDER BY created_at", (rid,)).fetchall()]


def get_case(path: str, cid: str) -> dict | None:
    import json
    with connect(path) as c:
        r = c.execute("SELECT * FROM swarm_cases WHERE id = ?", (cid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["result"] = json.loads(d["result"]) if d.get("result") else None
    return d


# ---- interdictions (bank-wide watchlist hits) --------------------------------

def add_interdiction(path: str, d: dict) -> dict:
    with connect(path) as c:
        cur = c.execute(
            "INSERT INTO interdictions (tx_id, payer_id, payee_id, amount_cents, action, reason, engagement_id, "
            "source, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (d.get("tx_id"), d.get("payer_id"), d.get("payee_id"), d.get("amount_cents"), d["action"],
             d.get("reason"), d.get("engagement_id"), d.get("source"), now()))
        return dict(c.execute("SELECT * FROM interdictions WHERE id = ?", (cur.lastrowid,)).fetchone())


def list_interdictions(path: str, limit: int = 100) -> list[dict]:
    with connect(path) as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM interdictions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]


def update_interdiction(path: str, row_id: int, **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in ("action", "reason", "source")}
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect(path) as c:
        c.execute(f"UPDATE interdictions SET {cols} WHERE id = ?", (*fields.values(), row_id))


def interdiction_for_tx(path: str, tx_id: str) -> dict | None:
    with connect(path) as c:
        r = c.execute("SELECT * FROM interdictions WHERE tx_id = ? ORDER BY id DESC LIMIT 1", (tx_id,)).fetchone()
    return dict(r) if r else None
