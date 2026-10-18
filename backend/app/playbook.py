"""The attacker's playbook, extracted from an engagement's event timeline.

Once someone is inside the decoy account, every move they make is a bank operation through the
proxy, and every bank operation is attributed to a session (sid) and an actor: `agent` is the decoy's
own browser doing what the email said; `external` is anyone else — i.e. a third party using the
phished credentials. This module reads those events and answers: who was it, what did they look at,
what did they change, how did they move the money, how fast, and in what order. Pure function over
stored events; safe to recompute on every refresh.

Stages (the account-takeover kill chain):
  access   — password accepted, one-time code cleared, session opened
  recon    — reads before the first money movement (account list, history, profile)
  lockout  — contact details changed (where the OTP / alerts go) — before or after the drain
  drain    — transfers out: internal sweeps (savings→checking) vs external, declines, structuring
  cash-out — withdrawals / purchases downstream
"""
from __future__ import annotations

from datetime import datetime
from hashlib import sha1

LIMIT_DEFAULT = 500000  # cents; the proxy's per-transfer ceiling (TRANSFER_LIMIT_CENTS)

_READ_LABEL = [
    ("/transactions", "transaction history"),
    ("/accounts", "account list / balances"),
    ("/customers", "profile"),
    ("/auth/profile", "contact details"),
]


def _ts(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except (ValueError, TypeError):
        return None


def _secs(a: datetime | None, b: datetime | None) -> float | None:
    return round((b - a).total_seconds(), 1) if a and b else None


def _ua_family(ua: str) -> str:
    u = (ua or "").lower()
    if "headlesschrome" in u or "playwright" in u:
        return "headless chromium"
    if "python" in u or "httpx" in u or "curl" in u:
        return "script"
    if "mobile" in u or "iphone" in u or "android" in u:
        return "mobile browser"
    if "firefox" in u:
        return "firefox"
    if "safari" in u and "chrome" not in u:
        return "safari"
    if "edg/" in u:
        return "edge"
    if "chrome" in u:
        return "chrome"
    return "unknown"


def _own_accounts(events: list[dict]) -> set[str]:
    own: set[str] = set()
    for e in events:
        if e["type"] == "persona.created":
            own.update(e["data"].get("accounts") or [])
    return own


def sessions(events: list[dict]) -> list[dict]:
    """Group proxy telemetry by session. Events without a sid (password_ok, login.failed) attach to
    the next session opened by the same actor, or stand alone as attempts."""
    own = _own_accounts(events)
    out: dict[str, dict] = {}
    order: list[str] = []
    pending_pw: list[dict] = []

    def session(sid: str, actor: str, e: dict) -> dict:
        if sid not in out:
            d = e.get("data") or {}
            out[sid] = {"sid": sid, "actor": actor or "external", "ip": d.get("ip"), "ua": d.get("ua"),
                        "ua_family": _ua_family(d.get("ua")), "opened_at": e["created_at"],
                        "password_ok_at": None, "login_at": None, "reads": [], "money": [], "declines": [],
                        "contact_changes": [], "requests": 0}
            order.append(sid)
        return out[sid]

    for e in events:
        if e["source"] != "proxy":
            continue
        d = e.get("data") or {}
        t = e["type"]
        if t == "login.password_ok":
            pending_pw.append(e)
            continue
        sid = d.get("sid")
        if not sid:
            continue
        s = session(sid, d.get("actor"), e)
        if t == "session.login":
            s["login_at"] = e["created_at"]
            # The password check that preceded this login (same actor, most recent).
            for pw in reversed(pending_pw):
                if (pw["data"] or {}).get("actor", "external") == s["actor"]:
                    s["password_ok_at"] = pw["created_at"]
                    pending_pw.remove(pw)
                    break
        elif t == "request":
            s["requests"] += 1
            if d.get("method") == "GET":
                label = next((lab for frag, lab in _READ_LABEL if frag in (d.get("path") or "")), None)
                if label and not s["money"]:  # only reads BEFORE the first money movement count as recon
                    s["reads"].append({"at": e["created_at"], "what": label, "path": d.get("path")})
        elif t == "money.attempt":
            internal = d.get("payee_id") in own
            s["money"].append({"at": e["created_at"], "kind": d.get("kind"), "amount_cents": int(d.get("amount_cents") or 0),
                               "payer_id": d.get("payer_id"), "payee_id": d.get("payee_id"),
                               "internal": internal, "status": d.get("status"), "reason": d.get("reason"),
                               "tx_id": d.get("tx_id")})
        elif t == "transfer.declined":
            s["declines"].append({"at": e["created_at"], "amount_cents": int(d.get("amount_cents") or 0),
                                  "limit_cents": int(d.get("limit_cents") or 0), "payee_id": d.get("payee_id"),
                                  "payer_id": d.get("payer_id"), "reason": d.get("reason")})
        elif t == "contact.changed":
            s["contact_changes"].append({"at": e["created_at"], "fields": d.get("fields") or [],
                                         "changes": d.get("changes") or {}, "source": d.get("source", "profile")})
    return [out[k] for k in order]


def _fingerprint_ops(s: dict, own: set[str]) -> str:
    """A compact op-sequence: L login, R recon read, C contact change, S internal sweep,
    X external transfer, D declined attempt, W withdrawal/purchase. The order IS the behaviour."""
    items: list[tuple[str, str]] = []
    if s["login_at"]:
        items.append((s["login_at"], "L"))
    items += [(r["at"], "R") for r in s["reads"]]
    items += [(c["at"], "C") for c in s["contact_changes"]]
    items += [(d["at"], "D") for d in s["declines"]]
    for m in s["money"]:
        if m["status"] != "accepted":
            items.append((m["at"], "D"))
        elif m["kind"] in ("withdrawal", "purchase"):
            items.append((m["at"], "W"))
        elif m["internal"]:
            items.append((m["at"], "S"))
        else:
            items.append((m["at"], "X"))
    items.sort(key=lambda x: x[0])
    seq = "".join(code for _, code in items)
    # Collapse runs of recon reads so "RRRRR" and "RRR" fingerprint alike.
    out = []
    for ch in seq:
        if not (ch == "R" and out and out[-1] == "R"):
            out.append(ch)
    return "".join(out)


def analyse(events: list[dict], limit_cents: int = LIMIT_DEFAULT) -> dict:
    """The playbook for one engagement. `subject` is the session we profile: the first third-party
    session if there is one (the scammer), else the decoy agent's own compliance run."""
    own = _own_accounts(events)
    sess = sessions(events)
    external = [s for s in sess if s["actor"] != "agent"]
    subject = (external or sess or [None])[0]
    pw_attempts = [e for e in events if e["type"] in ("login.password_ok", "login.failed")
                   and (e["data"] or {}).get("actor", "external") != "agent"]

    if subject is None:
        return {"subject": None, "sessions": [], "third_party": False, "stages": [], "metrics": {},
                "fingerprint": None, "profile": None, "summary": "No one has signed in to the decoy yet.",
                "password_attempts": len(pw_attempts)}

    login = _ts(subject["login_at"]) or _ts(subject["opened_at"])
    accepted = [m for m in subject["money"] if m["status"] == "accepted"]
    external_out = [m for m in accepted if not m["internal"] and m["kind"] == "transfer"]
    sweeps = [m for m in accepted if m["internal"] and m["kind"] == "transfer"]
    cashout = [m for m in accepted if m["kind"] in ("withdrawal", "purchase")]
    first_move = min((_ts(m["at"]) for m in subject["money"] + subject["declines"] if _ts(m["at"])), default=None)
    last_move = max((_ts(m["at"]) for m in accepted if _ts(m["at"])), default=None)
    moved_out = sum(m["amount_cents"] for m in external_out)
    mules = sorted({m["payee_id"] for m in external_out if m["payee_id"]})
    declined = subject["declines"] + [m for m in subject["money"] if m["status"] == "rejected"]
    under_limit = [m for m in external_out if limit_cents and 0.6 * limit_cents <= m["amount_cents"] < limit_cents]
    structured = len(under_limit) >= 2 or (bool(subject["declines"]) and len(external_out) >= 2)
    round_amounts = sum(1 for m in external_out if m["amount_cents"] % 10000 == 0)
    lockout = subject["contact_changes"]
    lockout_first = bool(lockout and first_move and _ts(lockout[0]["at"]) and _ts(lockout[0]["at"]) < first_move)
    t_first = _secs(login, first_move)
    t_drain = _secs(first_move, last_move) if len(accepted) > 1 else 0.0 if accepted else None

    stages = [
        {"key": "access", "title": "Access", "done": bool(subject["login_at"] or subject["password_ok_at"]),
         "at": subject["login_at"] or subject["opened_at"],
         "lines": [f"{'decoy agent' if subject['actor'] == 'agent' else 'third party'} · {subject['ua_family']}"
                   + (f" · {subject['ip']}" if subject["ip"] else ""),
                   "password accepted" + (f", OTP cleared {_secs(_ts(subject['password_ok_at']), login)}s later" if subject["password_ok_at"] and login else ""),
                   *([f"{len(pw_attempts)} earlier password attempt(s) from outside"] if pw_attempts and subject["actor"] != "agent" else [])]},
        {"key": "recon", "title": "Recon", "done": bool(subject["reads"]), "at": subject["reads"][0]["at"] if subject["reads"] else None,
         "lines": [f"{len(subject['reads'])} read(s) before touching money: " + ", ".join(dict.fromkeys(r["what"] for r in subject["reads"]))]
         if subject["reads"] else ["went straight for the money — no recon"]},
        {"key": "lockout", "title": "Lockout", "done": bool(lockout), "at": lockout[0]["at"] if lockout else None,
         "lines": [f"changed {', '.join(c['fields'])}" + (f" → {c['changes'].get('email', {}).get('to')}" if c['changes'].get('email') else "")
                   + (" — BEFORE moving money" if lockout_first else " — after the drain") for c in lockout]
         if lockout else ["contact details left alone"]},
        {"key": "drain", "title": "Drain", "done": bool(accepted or declined), "at": subject["money"][0]["at"] if subject["money"] else (subject["declines"][0]["at"] if subject["declines"] else None),
         "lines": [*( [f"swept {len(sweeps)} internal transfer(s) first (savings → checking)"] if sweeps else []),
                   *( [f"{len(external_out)} transfer(s) out · ${moved_out / 100:,.2f} → {', '.join(x[-6:] for x in mules) or '?'}"] if external_out else []),
                   *( [f"{len(declined)} attempt(s) refused" + (f" (hit the ${limit_cents / 100:,.0f} limit)" if subject["declines"] else "")] if declined else []),
                   *( ["structured underneath the limit after a refusal" if subject["declines"] else "amounts kept just under the limit"] if structured else []),
                   *( [f"{round_amounts} round-number amount(s)"] if round_amounts else [])]
         or ["no money moved"]},
        {"key": "cashout", "title": "Cash-out", "done": bool(cashout), "at": cashout[0]["at"] if cashout else None,
         "lines": [f"{len(cashout)} withdrawal/purchase(s) · ${sum(m['amount_cents'] for m in cashout) / 100:,.2f}"] if cashout
         else ["nothing cashed out from the decoy itself (follow the mule)"]},
    ]

    fp_ops = _fingerprint_ops(subject, own)
    fp_src = f"{fp_ops}|{subject['ua_family']}|{'S' if structured else '-'}|{'L' if lockout_first else '-'}"
    fingerprint = {"ops": fp_ops, "ua_family": subject["ua_family"], "structured": structured,
                   "lockout_first": lockout_first, "hash": sha1(fp_src.encode()).hexdigest()[:10]}

    # A coarse read of who this is. Heuristic, and labelled as such in the UI.
    if subject["actor"] == "agent":
        profile = {"label": "decoy compliance", "why": "the decoy's own browser doing exactly what the email said"}
    elif t_first is not None and t_first < 15 and not subject["reads"]:
        profile = {"label": "scripted drain", "why": f"money moving {t_first}s after login with no recon — automated"}
    elif lockout_first:
        profile = {"label": "organised account-takeover crew", "why": "locked the victim out (changed contact details) before moving money"}
    elif sweeps and structured:
        profile = {"label": "experienced casher", "why": "swept savings first and split the drain under the limit"}
    elif subject["reads"] and t_first is not None and t_first > 60:
        profile = {"label": "human operator", "why": f"read the account for {t_first}s before acting"}
    else:
        profile = {"label": "opportunist", "why": "single-pass drain, no lockout, no structuring"}

    metrics = {
        "actor": subject["actor"], "sid": subject["sid"], "ip": subject["ip"], "ua_family": subject["ua_family"],
        "secs_login_to_first_move": t_first, "secs_drain_window": t_drain,
        "recon_reads": len(subject["reads"]), "internal_sweeps": len(sweeps), "external_transfers": len(external_out),
        "declined_attempts": len(declined), "structured": structured, "lockout": bool(lockout), "lockout_first": lockout_first,
        "moved_out_cents": moved_out, "mules": mules, "cashout_ops": len(cashout), "limit_cents": limit_cents,
        "third_party_sessions": len(external), "password_attempts_outside": len(pw_attempts),
    }
    parts = []
    if subject["actor"] != "agent":
        parts.append("a third party signed in with the phished credentials")
    if t_first is not None:
        parts.append(f"first money movement {t_first}s after login")
    if external_out:
        parts.append(f"${moved_out / 100:,.2f} out to {len(mules)} account(s)")
    if structured:
        parts.append("structured under the transfer limit")
    if lockout:
        parts.append("contact details changed" + (" first" if lockout_first else ""))
    return {"subject": subject["sid"], "third_party": bool(external), "sessions": sess, "stages": stages,
            "metrics": metrics, "fingerprint": fingerprint, "profile": profile,
            "summary": "; ".join(parts) + "." if parts else "signed in, nothing moved yet.",
            "password_attempts": len(pw_attempts)}
