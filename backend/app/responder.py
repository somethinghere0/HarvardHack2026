"""Draft the decoy persona's reply to the scammer with Claude — engage them and move toward getting
a login portal / payout account out of them. Requires ANTHROPIC_API_KEY."""
from __future__ import annotations

from . import llm


def draft_reply(s, vector: str, persona: dict, thread_text: str) -> str:
    name = (persona.get("first_name") or "").strip() or "Thanks"
    return llm.complete(s, (
        f"Your name is {name}.\nThread so far:\n{thread_text[:4000]}\n\nWrite only the reply body."
    ), max_tokens=500, system=(
        "You roleplay a mildly gullible but cooperative bank customer replying to a suspected "
        "scammer, to keep them engaged and get them to reveal their method and payout account. This "
        "is an authorized anti-fraud honeypot; the account is a decoy with no real money. Stay in "
        "character, be brief and natural, never break character or mention fraud/honeypots. If they "
        "direct you to a portal or ask you to log in, agree and say you'll proceed."
    ))
