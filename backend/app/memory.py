"""Scam memory: everything the honeypot has learned from every scam it has ever detonated.

Each engagement leaves a full event timeline in the database. This module reads all of them and
builds the long-term picture the ops dashboard's "scam memory" tab shows: one dossier per scam
(who sent it, what it asked for, where the link went, how the money moved, who received it, how the
operator behaved) plus the cross-scam patterns — the same lure themes, sender domains, phishing hosts,
mule accounts and playbook fingerprints showing up again and again. Pure function over stored rows;
nothing is cached, so the view is always as current as the database.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from urllib.parse import urlparse

from . import db, playbook

SCAM_STATUSES = {"compromised", "confirmed", "armed", "drained"}

# Lure themes: the social-engineering hook an email uses. A scam usually mixes two or three.
THEMES = [
    ("urgency", r"\b(urgent|immediate(ly)?|right away|within (24|48) hours|expires?|final notice|act now|asap)\b"),
    ("fear / account threat", r"\b(compromised|suspended|locked|unauthori[sz]ed|suspicious|blocked|breach|fraud(ulent)?|hacked)\b"),
    ("verify / confirm", r"\b(verify|confirm|validate|re-?activate|update your (details|information|account))\b"),
    ("refund / payout", r"\b(refund|rebate|reimburse|payout|owed|credit(ed)? to you|you('ve| have) been selected|prize|won)\b"),
    ("tax / government", r"\b(irs|tax|hmrc|treasury|stimulus|social security|government)\b"),
    ("invoice / payment change", r"\b(invoice|payment instructions|new (bank|account) details|wire|remit|rent|updated (bank|payment))\b"),
    ("delivery / parcel", r"\b(package|parcel|delivery|shipment|courier|customs fee)\b"),
    ("authority impersonation", r"\b(security team|fraud department|support team|it department|ceo|customer service|bank of usa)\b"),
    ("new device / login", r"\b(new device|sign-?in|login attempt|unrecognized|unknown device)\b"),
]
_THEME_RE = [(name, re.compile(pat, re.I)) for name, pat in THEMES]


def _domain(addr: str | None) -> str | None:
    if not addr:
        return None
    m = re.search(r"@([\w.-]+)", addr)
    return m.group(1).lower() if m else None


def _host(url: str | None) -> str | None:
    try:
        return (urlparse(url).hostname or "").lower() or None
    except Exception:
        return None


def themes_of(subject: str | None, body: str | None) -> list[str]:
    text = f"{subject or ''}\n{body or ''}"
    return [name for name, rx in _THEME_RE if rx.search(text)]


def _is_scam(eng: dict, msg: dict | None) -> bool:
    return (msg or {}).get("verdict") == "scam" or eng.get("status") in SCAM_STATUSES


def dossier(path: str, eng: dict, msg: dict | None, limit_cents: int, interdictions: list[dict]) -> dict:
    """Everything worth remembering about one scam, flattened for comparison with the others."""
    eid = eng["id"]
    events = db.list_events(path, eid)
    own: set[str] = set()
    for e in events:
        if e["type"] == "persona.created":
            own.update(e["data"].get("accounts") or [])

    outflows, seen = [], set()
    for e in events:
        d = e["data"]
        if e["type"] not in ("transfer.created", "withdrawal.created") or d.get("payer_id") not in own \
                or d.get("payee_id") in own:
            continue
        if d.get("tx_id") in seen:
            continue
        seen.add(d.get("tx_id"))
        outflows.append(d)
    mules = sorted({d.get("payee_id") for d in outflows if d.get("payee_id")})
    moved = sum(int(d.get("amount_cents") or 0) for d in outflows)

    link = next((e["data"].get("url") for e in events if e["type"] == "portal.detected"), None)
    leaks = [e["data"] for e in events if e["type"] == "secret.disclosed"]
    intruders = [e["data"] for e in events if e["type"] == "credential.used_by_third_party"]
    known_mule = [e["data"].get("engagement_id") for e in events if e["type"] == "watchlist.match"]
    pb = playbook.analyse(events, limit_cents)
    fp = pb.get("fingerprint") or {}
    metrics = pb.get("metrics") or {}
    stops = [i for i in interdictions if i.get("engagement_id") == eid]
    sender = (msg or {}).get("sender") or eng.get("scammer_email")
    subject = (msg or {}).get("subject") or eng.get("subject")

    return {
        "id": eid, "at": eng["created_at"], "status": eng["status"], "grade": eng.get("grade") or (msg or {}).get("grade"),
        "risk_score": eng.get("risk_score") or 0, "tags": eng.get("tags") or [],
        "subject": subject, "sender": sender, "sender_domain": _domain(sender),
        "vector": (msg or {}).get("vector"), "reason": (msg or {}).get("reason") or eng.get("summary"),
        "themes": themes_of(subject, (msg or {}).get("body")),
        "link": link, "phish_host": _host(link),
        "secrets_leaked": sorted({d.get("kind", "secret") for d in leaks}),
        "leaked_to": sorted({d.get("host") or d.get("channel") or "?" for d in leaks}),
        "moved_out_cents": moved, "transfers_out": len(outflows), "mules": mules,
        "third_party_logins": len(intruders),
        "intruder_ips": sorted({d.get("ip") for d in intruders if d.get("ip")}),
        "known_mule_from": sorted({x for x in known_mule if x}),
        "profile": (pb.get("profile") or {}).get("label"),
        "profile_why": (pb.get("profile") or {}).get("why"),
        "fingerprint": fp.get("hash"), "ops": fp.get("ops"), "ua_family": fp.get("ua_family"),
        "structured": bool(metrics.get("structured")), "lockout": bool(metrics.get("lockout")),
        "secs_to_first_move": metrics.get("secs_login_to_first_move"),
        "recon_reads": metrics.get("recon_reads", 0),
        "blocked": len(stops), "blocked_cents": sum(int(i.get("amount_cents") or 0) for i in stops),
    }


def _bucket(items: list[dict], key: str, multi: bool = False) -> list[dict]:
    """Group dossiers by one field (or each value of a list field) and roll up what they have in common."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for d in items:
        vals = d.get(key) or []
        if not multi:
            vals = [vals] if vals else []
        for v in vals:
            groups[str(v)].append(d)
    out = []
    for v, ds in groups.items():
        out.append({"value": v, "count": len(ds), "moved_out_cents": sum(x["moved_out_cents"] for x in ds),
                    "engagements": [x["id"] for x in ds], "last_seen": max(x["at"] for x in ds),
                    "vectors": sorted({x["vector"] for x in ds if x["vector"]})})
    out.sort(key=lambda g: (-g["count"], -g["moved_out_cents"], g["value"]))
    return out


def build(path: str, limit_cents: int) -> dict:
    engagements = db.list_engagements(path)
    msgs = {m["engagement_id"]: m for m in reversed(db.list_messages(path, 5000)) if m.get("engagement_id")}
    interdictions = db.list_interdictions(path, 1000)
    scams = [dossier(path, e, msgs.get(e["id"]), limit_cents, interdictions)
             for e in engagements if _is_scam(e, msgs.get(e["id"]))]
    scams.sort(key=lambda d: d["at"], reverse=True)

    # Recurring playbooks: the same op-sequence fingerprint seen in more than one scam is one crew's
    # habit, not a coincidence.
    fps = _bucket([d for d in scams if d["fingerprint"]], "fingerprint")
    for g in fps:
        d0 = next(x for x in scams if x["fingerprint"] == g["value"])
        g.update({"ops": d0["ops"], "ua_family": d0["ua_family"], "profile": d0["profile"],
                  "structured": d0["structured"], "lockout": d0["lockout"]})

    mules = _bucket(scams, "mules", multi=True)
    for g in mules:
        g["grade"] = "confirmed" if any(x["grade"] == "confirmed" for x in scams if g["value"] in x["mules"]) else "likely"

    verdict_counts = Counter((msgs.get(e["id"]) or {}).get("verdict") or "none" for e in engagements)
    totals = {
        "scams": len(scams), "detonated": len(engagements),
        "safe": verdict_counts.get("safe", 0), "inconclusive": verdict_counts.get("error", 0),
        "confirmed": sum(1 for d in scams if d["grade"] == "confirmed"),
        "moved_out_cents": sum(d["moved_out_cents"] for d in scams),
        "mules": len(mules), "phish_hosts": len({d["phish_host"] for d in scams if d["phish_host"]}),
        "sender_domains": len({d["sender_domain"] for d in scams if d["sender_domain"]}),
        "recurring_playbooks": sum(1 for g in fps if g["count"] > 1),
        "repeat_mules": sum(1 for g in mules if g["count"] > 1),
        "blocked": len(interdictions),
        "blocked_cents": sum(int(i.get("amount_cents") or 0) for i in interdictions),
        "credential_leaks": sum(1 for d in scams if d["secrets_leaked"]),
        "third_party_logins": sum(d["third_party_logins"] for d in scams),
        "first_seen": min((d["at"] for d in scams), default=None),
        "last_seen": max((d["at"] for d in scams), default=None),
    }
    return {
        "totals": totals,
        "scams": scams,
        "patterns": {
            "themes": _bucket(scams, "themes", multi=True),
            "vectors": _bucket(scams, "vector"),
            "sender_domains": _bucket(scams, "sender_domain"),
            "phish_hosts": _bucket(scams, "phish_host"),
            "profiles": _bucket(scams, "profile"),
            "tags": _bucket(scams, "tags", multi=True),
            "fingerprints": fps,
            "mules": mules,
        },
        "interdictions": interdictions[:50],
    }
