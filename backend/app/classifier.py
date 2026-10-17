"""Classifies an inbound email: is it a scam, and which vector. Uses Claude when ANTHROPIC_API_KEY
is set, otherwise a keyword heuristic. Output drives whether an engagement is opened."""
from __future__ import annotations

import json

_VECTORS = {
    "credential_phishing": ["verify your account", "confirm your identity", "login", "suspended",
                            "unusual activity", "reset your password", "secure your account"],
    "payment_fraud": ["wire transfer", "update bank details", "new account number", "invoice",
                      "payment overdue", "remittance"],
    "advance_fee": ["lottery", "inheritance", "beneficiary", "processing fee", "prince", "claim your"],
    "impersonation": ["ceo", "gift card", "urgent request", "are you available", "need a favor"],
}


def _heuristic(subject: str, body: str) -> dict:
    text = f"{subject}\n{body}".lower()
    best, score = None, 0
    for vector, kws in _VECTORS.items():
        hits = sum(1 for k in kws if k in text)
        if hits > score:
            best, score = vector, hits
    urgency = any(w in text for w in ("urgent", "immediately", "within 24 hours", "act now", "final notice"))
    is_scam = score >= 1
    confidence = min(0.95, 0.4 + 0.2 * score + (0.1 if urgency else 0))
    return {"is_scam": is_scam, "vector": best or "unknown", "confidence": round(confidence, 2),
            "reason": f"matched {score} indicator(s)" + (", urgency language" if urgency else "")}


def classify(s, sender: str, subject: str, body: str) -> dict:
    if not s.anthropic_api_key:
        return _heuristic(subject, body)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=s.anthropic_api_key)
        prompt = (
            "You are a fraud triage classifier for a bank's abuse team. Classify this inbound email. "
            "Reply with ONLY compact JSON: "
            '{"is_scam": bool, "vector": one of '
            '["credential_phishing","payment_fraud","advance_fee","impersonation","unknown"], '
            '"confidence": 0..1, "reason": short string}.\n\n'
            f"From: {sender}\nSubject: {subject}\n\n{body[:4000]}"
        )
        msg = client.messages.create(model=s.anthropic_model, max_tokens=300,
                                     messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        start, end = text.find("{"), text.rfind("}")
        return json.loads(text[start:end + 1])
    except Exception:
        return _heuristic(subject, body)
