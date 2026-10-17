"""Builds a decoy persona for an engagement: a fictitious identity, a Honeybank login, and a Nessie
customer with a couple of accounts and realistic-looking seeded history. All created through the
proxy's real signup path so the scammer-facing login behaves exactly like any other user's."""
from __future__ import annotations

import random
import secrets

from . import db
from .identity import generate_identity
from .proxy_client import ProxyClient

# A little seeded history so an account doesn't look brand-new (amounts in cents).
_SEED_DEPOSITS = [
    ("Payroll — direct deposit", 285000, 342000),
    ("Payroll — direct deposit", 285000, 342000),
    ("Tax refund", 40000, 180000),
    ("Zelle from family", 5000, 45000),
]


def _persona_email(gmail_address: str, pid: str) -> str:
    local, _, domain = gmail_address.partition("@")
    return f"{local}+persona_{pid}@{domain}" if domain else f"persona_{pid}@example.com"


def _username(first: str, last: str) -> str:
    return f"{first}.{last}{random.randint(10, 999)}".lower()


async def create_persona(s, engagement_id: str) -> dict:
    pid = secrets.token_hex(6)
    ident = await generate_identity(s)
    username = _username(ident["first_name"], ident["last_name"])
    password = secrets.token_urlsafe(12)
    email = _persona_email(s.gmail_address, pid)

    proxy = ProxyClient(s.proxy_url)
    res = await proxy.signup({
        "username": username, "password": password,
        "first_name": ident["first_name"], "last_name": ident["last_name"],
        "address": ident["address"],
    })
    token, customer_id = res["token"], res["customer_id"]

    db.create_persona(s.db_path, {
        "id": pid, "engagement_id": engagement_id, "username": username, "password": password,
        "email": email, "customer_id": customer_id,
        "first_name": ident["first_name"], "last_name": ident["last_name"],
    })

    # Open a checking + savings account and seed each with believable history.
    checking = await proxy.open_account(token, customer_id,
                                        {"type": "Checking", "nickname": "Everyday Checking", "balance_cents": 0})
    savings = await proxy.open_account(token, customer_id,
                                       {"type": "Savings", "nickname": "Savings", "balance_cents": 0})
    for desc, lo, hi in _SEED_DEPOSITS:
        acct = random.choice([checking, savings])
        await proxy.deposit(token, _acct_id(acct), random.randint(lo, hi), desc)

    db.add_event(s.db_path, engagement_id, "system", "persona.created", {
        "persona_id": pid, "username": username, "email": email, "customer_id": customer_id,
        "name": f"{ident['first_name']} {ident['last_name']}",
        "accounts": [_acct_id(checking), _acct_id(savings)],
    })
    return {"persona_id": pid, "username": username, "password": password, "email": email,
            "customer_id": customer_id,
            "accounts": {"checking": _acct_id(checking), "savings": _acct_id(savings)}}


def _acct_id(a: dict) -> str:
    return a.get("id") or a.get("_id")
