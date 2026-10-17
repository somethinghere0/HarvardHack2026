"""Turns an engagement's raw event timeline into fraud indicators and a risk score — the intel
product. Pure function over the stored events; safe to recompute on every new event."""
from __future__ import annotations

from datetime import datetime

from . import db

# Thresholds (cents).
LARGE_TRANSFER = 100000        # $1,000 single transfer
STRUCTURING_CEILING = 100000   # transfers deliberately kept just under a reporting line
STRUCTURING_MIN_COUNT = 3

_WEIGHTS = {
    "external_payee": 20,      # money leaving to an account outside the persona
    "large_transfer": 20,
    "rapid_drain": 20,         # money moved within minutes of the login
    "structuring": 25,         # several sub-threshold transfers (laundering tell)
    "full_drain": 25,          # account emptied
    "contact_change": 15,      # locking the victim out
    "new_payee": 10,
}

_LABELS = {
    "external_payee": "Funds sent to an external account",
    "large_transfer": "Large single transfer",
    "rapid_drain": "Money moved within minutes of login",
    "structuring": "Multiple sub-threshold transfers (structuring)",
    "full_drain": "Account drained",
    "contact_change": "Contact info changed (victim lockout)",
    "new_payee": "New payee added",
}


def _ts(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def compute(path: str, engagement_id: str) -> dict:
    events = db.list_events(path, engagement_id)
    persona_accounts: set[str] = set()
    for e in events:
        if e["type"] == "persona.created":
            persona_accounts.update(e["data"].get("accounts", []))

    login_ts = next((_ts(e["created_at"]) for e in events
                     if e["type"] in ("session.login", "login.success")), None)

    transfers = [e for e in events if e["type"] in ("transfer.created", "transaction.completed")
                 and e["data"].get("payer_id")]
    tags: set[str] = set()
    sub_threshold = 0

    for e in transfers:
        d = e["data"]
        amt = int(d.get("amount_cents") or 0)
        payee = d.get("payee_id")
        if payee and payee not in persona_accounts:
            tags.add("external_payee")
        if amt >= LARGE_TRANSFER:
            tags.add("large_transfer")
        if 0 < amt < STRUCTURING_CEILING:
            sub_threshold += 1
        t = _ts(e["created_at"])
        if login_ts and t and (t - login_ts).total_seconds() <= 600:
            tags.add("rapid_drain")

    if sub_threshold >= STRUCTURING_MIN_COUNT:
        tags.add("structuring")
    if any(e["type"] == "account.balance_changed" and int(e["data"].get("balance_cents", 1)) <= 0
           for e in events):
        tags.add("full_drain")
    if any(e["type"] in ("profile.updated", "contact.changed") for e in events):
        tags.add("contact_change")
    if any(e["type"] == "payee.added" for e in events):
        tags.add("new_payee")

    score = min(100, sum(_WEIGHTS.get(t, 0) for t in tags))
    return {
        "risk_score": score,
        "tags": sorted(tags),
        "indicators": [{"tag": t, "label": _LABELS.get(t, t), "weight": _WEIGHTS.get(t, 0)}
                       for t in sorted(tags)],
    }


def recompute_and_store(path: str, engagement_id: str) -> dict:
    result = compute(path, engagement_id)
    status_bump = {}
    if "full_drain" in result["tags"]:
        status_bump["status"] = "drained"
    elif result["tags"]:
        status_bump["status"] = "active"
    db.update_engagement(path, engagement_id, risk_score=result["risk_score"],
                         tags=result["tags"], **status_bump)
    return result
