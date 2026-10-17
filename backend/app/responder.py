"""Drafts the decoy persona's replies to the scammer — the part that keeps the thread alive and, when
the scammer asks the victim to log in somewhere, hands over the decoy Honeybank credentials (never a
real account). Uses Claude when configured, otherwise templated replies keyed off the scam vector."""
from __future__ import annotations

_TEMPLATES = {
    "credential_phishing": (
        "Hi,\n\nThanks for letting me know — I don't want my account suspended. "
        "I tried the link you sent. Could you confirm this is the right place to sign in? "
        "I'll go ahead and verify now.\n\nThanks,\n{name}"
    ),
    "payment_fraud": (
        "Hi,\n\nGot it. I can send the payment. Can you resend the exact account details so I make "
        "sure it goes to the right place?\n\nBest,\n{name}"
    ),
    "advance_fee": (
        "Hello,\n\nThis is wonderful news. What do you need from me to release the funds? "
        "Happy to complete the next step.\n\nRegards,\n{name}"
    ),
    "impersonation": (
        "Hi,\n\nOf course, happy to help. Just let me know exactly what you need and I'll take care "
        "of it right away.\n\n{name}"
    ),
}
_DEFAULT = "Hi,\n\nThanks for reaching out — can you tell me the next step?\n\n{name}"


def draft_reply(s, vector: str, persona: dict, thread_text: str) -> str:
    name = (persona.get("first_name") or "").strip() or "Thanks"
    if not s.anthropic_api_key:
        return _TEMPLATES.get(vector, _DEFAULT).format(name=name)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=s.anthropic_api_key)
        prompt = (
            "You roleplay a mildly gullible but cooperative bank customer replying to a suspected "
            "scammer, to keep them engaged and get them to reveal their method and payout account. "
            "This is an authorized anti-fraud honeypot; the account is a decoy with no real money. "
            "Stay in character, be brief and natural, never break character or mention fraud/honeypots. "
            "If they direct you to a portal or ask you to log in, agree and say you'll proceed.\n\n"
            f"Your name is {name}.\nThread so far:\n{thread_text[:4000]}\n\nWrite only the reply body."
        )
        msg = client.messages.create(model=s.anthropic_model, max_tokens=500,
                                     messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
    except Exception:
        return _TEMPLATES.get(vector, _DEFAULT).format(name=name)
