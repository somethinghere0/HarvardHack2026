"""Classify an inbound email with Claude: is it a scam, and which vector. Requires ANTHROPIC_API_KEY."""
from __future__ import annotations

from . import llm

VECTORS = ["credential_phishing", "payment_fraud", "advance_fee", "impersonation", "unknown"]


def classify(s, sender: str, subject: str, body: str) -> dict:
    data = llm.complete_json(s, (
        "You are a bank fraud-triage classifier. Classify this inbound email. Return ONLY JSON: "
        '{"is_scam": bool, "vector": one of '
        f"{VECTORS}, "
        '"confidence": 0..1, "reason": short string, '
        '"portal_url": the URL the email wants the victim to visit, or null}.\n\n'
        f"From: {sender}\nSubject: {subject}\n\n{body[:4000]}"
    ), max_tokens=400)
    if data.get("vector") not in VECTORS:
        data["vector"] = "unknown"
    return data
