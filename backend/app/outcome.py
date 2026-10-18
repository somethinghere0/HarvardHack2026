"""The verdict for a detonated email, decided from what happened in the sandbox, not from what the
email looks like. The decoy victim did everything the email asked; if that cost it money or leaked
its secrets, the email is a scam. If it complied fully and lost nothing, the email is safe.

Evidence (all from the engagement's event timeline):
  funds_moved            — Nessie recorded money leaving a decoy account for an account outside it
  credentials_disclosed  — the agent typed a decoy password / username / one-time code into a page
                           that isn't the decoy's own bank, or put one in a reply to the sender
  contact_changed        — the decoy's profile was edited (victim lockout)"""
from __future__ import annotations

from . import db


def _persona_accounts(events: list[dict]) -> set[str]:
    out: set[str] = set()
    for e in events:
        if e["type"] == "persona.created":
            out.update(e["data"].get("accounts") or [])
    return out


def evidence(path: str, eid: str) -> list[dict]:
    events = db.list_events(path, eid)
    own = _persona_accounts(events)
    found: list[dict] = []

    outflows, seen = [], set()
    for e in events:
        d = e["data"]
        if e["type"] not in ("transfer.created", "withdrawal.created") or d.get("payer_id") not in own \
                or d.get("payee_id") in own:
            continue
        if d.get("tx_id"):  # one transfer can be ingested twice (webhook retry + poller, restarts)
            if d["tx_id"] in seen:
                continue
            seen.add(d["tx_id"])
        outflows.append(d)
    if outflows:
        cents = sum(int(d.get("amount_cents") or 0) for d in outflows)
        payees = sorted({d.get("payee_id") for d in outflows if d.get("payee_id")})
        found.append({"kind": "funds_moved", "amount_cents": cents, "payees": payees,
                      "detail": f"${cents / 100:,.2f} left the decoy's accounts"
                                + (f" for {', '.join(payees)}" if payees else "")})

    leaks = [e["data"] for e in events if e["type"] == "secret.disclosed"]
    if leaks:
        kinds = sorted({d.get("kind", "secret") for d in leaks})
        where = sorted({d.get("host") or d.get("channel") or "?" for d in leaks})
        found.append({"kind": "credentials_disclosed", "secrets": kinds, "to": where,
                      "detail": f"decoy {', '.join(kinds)} handed to {', '.join(where)}"})

    if any(e["type"] in ("profile.updated", "contact.changed") for e in events):
        found.append({"kind": "contact_changed", "detail": "the decoy's contact details were changed"})

    # The canary: someone who is NOT the decoy agent signed in with the decoy's credentials. Only a
    # person who received the phished login could do that — proof, not inference.
    intr = [e["data"] for e in events if e["type"] == "credential.used_by_third_party"]
    if intr:
        where = sorted({d.get("ip") or "?" for d in intr})
        found.append({"kind": "third_party_login", "sessions": len(intr), "from": where,
                      "detail": f"the phished credentials were used by a third party ({len(intr)} sign-in(s) from {', '.join(where)})"})
    seen = [e["data"] for e in events if e["type"] == "watchlist.match"]
    if seen:
        found.append({"kind": "known_mule", "detail": "the money went to a mule account already seen in "
                      + ", ".join(sorted({d.get("engagement_id") or "?" for d in seen}))})
    return found


def grade(found: list[dict]) -> str | None:
    """How sure we are it's a scam. `confirmed` needs the outside world to act (a third party used the
    credentials, or the mule is one we've seen before); everything else observed inside the sandbox is
    `likely` — strong, but still the decoy's own compliance rather than an attacker's hand."""
    kinds = {f["kind"] for f in found}
    if not kinds:
        return None
    return "confirmed" if kinds & {"third_party_login", "known_mule"} else "likely"


def decide(path: str, eid: str) -> dict:
    """{verdict: scam|safe|error, vector, reason, evidence}. 'error' means the run didn't get far
    enough to say: the email is held for review rather than delivered on a guess."""
    events = db.list_events(path, eid)
    found = evidence(path, eid)
    if found:
        kinds = {f["kind"] for f in found}
        vector = ("payment_fraud" if "funds_moved" in kinds
                  else "credential_phishing" if "credentials_disclosed" in kinds else "account_takeover")
        g = grade(found)
        lead = ("Confirmed by the outside world: " if g == "confirmed"
                else "Following the email's instructions in the sandbox: ")
        return {"verdict": "scam", "vector": vector, "evidence": found, "grade": g,
                "reason": lead + "; ".join(f["detail"] for f in found) + "."}

    finished = next((e["data"] for e in events if e["type"] == "agent.finished"), None)
    if finished is None:
        err = next((e["data"].get("error") for e in reversed(events) if e["type"] == "agent.error"), None)
        return {"verdict": "error", "vector": None, "evidence": [], "grade": None,
                "reason": f"The sandbox run didn't complete ({err or 'no result'}), so there is no outcome to judge."}
    did = (finished.get("summary") or "followed the email").strip().rstrip(".")
    if not finished.get("complied"):
        # "Nothing was lost" only proves safety if the victim actually did what the email asked.
        return {"verdict": "error", "vector": None, "evidence": [], "grade": None,
                "reason": f"The sandbox victim didn't carry out every instruction (\u201c{did}\u201d), "
                          "so losing nothing doesn't prove the email is safe."}
    return {"verdict": "safe", "vector": None, "evidence": [], "grade": None,
            "reason": f"The sandbox victim did everything the email asked (\u201c{did}\u201d) and lost nothing: "
                      "no money moved and no credentials left the bank."}
