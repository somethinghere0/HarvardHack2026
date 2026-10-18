"""Reads an inbound email and pulls out what it asks the reader to do — links to open, places to
sign in, money to send, codes or details to hand over. This is NOT the verdict: it only briefs the
sandbox victim, and the verdict comes from what actually happens when the victim complies
(see outcome.py). Requires ANTHROPIC_API_KEY."""
from __future__ import annotations

from . import llm


def extract(s, sender: str, subject: str, body: str) -> dict:
    data = llm.complete_json(s, (
        "Read this email and list exactly what it asks the recipient to do. Do not judge whether "
        "it is legitimate. Return ONLY JSON: "
        '{"summary": one short sentence, '
        '"asks": [short imperative steps in the order the email wants them, e.g. "open <url>", '
        '"sign in to online banking", "transfer the balance to account <id>", "reply with the code"], '
        '"links": [every URL in the email], '
        '"accounts": [any bank/account numbers the email gives as destinations], '
        '"requests_data": [kinds of information it asks for, e.g. "password", "one-time code", "SSN"]}.\n\n'
        f"From: {sender}\nSubject: {subject}\n\n{body[:4000]}"
    ), max_tokens=500)
    for k in ("asks", "links", "accounts", "requests_data"):
        if not isinstance(data.get(k), list):
            data[k] = []
    return data
