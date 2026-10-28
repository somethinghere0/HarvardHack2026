"""Builds a decoy persona for an engagement: a fictitious identity, a Honeybank login, and a Nessie
customer with a couple of accounts and realistic-looking seeded history. All created through the
proxy's real signup path so the scammer-facing login behaves exactly like any other user's."""
from __future__ import annotations

import asyncio
import random
import secrets

import httpx

from . import db
from .identity import generate_identity
from .nessie import NessieAdmin, logged as nessie_logged
from .proxy_client import ProxyClient

# Seeded history so an account doesn't look brand-new (amounts in cents). The shape is a tripwire:
# savings holds more than checking, and each account stays under the bank's per-transfer limit, so
# a scammer who wants it all has to sweep savings first and split the drain — both observable.
_SEED_DEPOSITS = [
    ("checking", "Payroll — direct deposit", 142000, 171000),
    ("checking", "Payroll — direct deposit", 142000, 171000),
    ("savings", "Tax refund", 120000, 180000),
    ("savings", "Transfer from checking", 90000, 140000),
    ("savings", "Zelle from family", 5000, 45000),
]
_CARD_LIMIT_CENTS = 250000


def _phone() -> str:
    return f"({random.randint(201, 989)}) {random.randint(200, 999)}-{random.randint(1000, 9999)}"


def _persona_email(gmail_address: str, pid: str) -> str:
    local, _, domain = gmail_address.partition("@")
    return f"{local}+persona_{pid}@{domain}" if domain else f"persona_{pid}@example.com"


def _username(first: str, last: str) -> str:
    # Short random tail: the LLM reuses a few favourite names, so a 2-3 digit suffix collides
    # once the bank holds a few dozen personas (409 from /auth/signup).
    return f"{first}.{last}{random.randint(10, 999)}{secrets.token_hex(2)}".lower()


async def create_persona(s, engagement_id: str) -> dict:
    pid = secrets.token_hex(6)
    ident = await generate_identity(s)
    username = _username(ident["first_name"], ident["last_name"])
    password = secrets.token_urlsafe(12)
    email = _persona_email(s.gmail_address, pid)

    proxy = ProxyClient(s.proxy_url)
    for attempt in range(5):
        try:
            res = await proxy.signup({
                "username": username, "password": password,
                "first_name": ident["first_name"], "last_name": ident["last_name"],
                "address": ident["address"], "email": email, "phone": _phone(),
            })
            break
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 409 or attempt == 4:
                raise
            username = _username(ident["first_name"], ident["last_name"])  # taken: roll again
    token, customer_id = res["token"], res["customer_id"]

    db.create_persona(s.db_path, {
        "id": pid, "engagement_id": engagement_id, "username": username, "password": password,
        "email": email, "customer_id": customer_id,
        "first_name": ident["first_name"], "last_name": ident["last_name"],
    })

    # Open checking + savings + a credit card and seed believable history. Three products, three
    # questions for whoever breaks in: which do they drain first, do they sweep savings, do they
    # try a cash advance on the card.
    checking = await proxy.open_account(token, customer_id,
                                        {"type": "Checking", "nickname": "Everyday Checking", "balance_cents": 0})
    savings = await proxy.open_account(token, customer_id,
                                       {"type": "Savings", "nickname": "Savings", "balance_cents": 0})
    card = None
    try:
        card = await proxy.open_account(token, customer_id,
                                        {"type": "Credit Card", "nickname": "Quicksilver-ish Card", "balance_cents": 0,
                                         "credit_limit_cents": _CARD_LIMIT_CENTS})
    except Exception as e:
        print(f"[personas] couldn't open a credit card ({e}); continuing with checking + savings")
    admin = nessie_logged(s, engagement_id)
    for which, desc, lo, hi in _SEED_DEPOSITS:
        acct = checking if which == "checking" else savings
        tx = await _deposit_with_retry(proxy, token, _acct_id(acct), random.randint(lo, hi), desc)
        # Seeded history should already be posted, or the decoy shows a $0.00 balance and the
        # agent (or a real scammer) finds nothing to take.
        try:
            await admin.settle_transaction(tx.get("id") or tx.get("_id"))
        except Exception as e:
            print(f"[personas] couldn't settle seed deposit ({e}); it posts when Nessie's pending window ends")
    await admin.aclose()

    db.add_event(s.db_path, engagement_id, "system", "persona.created", {
        "persona_id": pid, "username": username, "email": email, "customer_id": customer_id,
        "name": f"{ident['first_name']} {ident['last_name']}",
        "accounts": [_acct_id(a) for a in (checking, savings, card) if a],
        "account_types": {_acct_id(a): a.get("type") for a in (checking, savings, card) if a},
    })
    return {"persona_id": pid, "username": username, "password": password, "email": email,
            "customer_id": customer_id,
            "accounts": {"checking": _acct_id(checking), "savings": _acct_id(savings),
                         **({"card": _acct_id(card)} if card else {})}}


async def _deposit_with_retry(proxy, token: str, account_id: str, amount_cents: int, desc: str, tries: int = 4) -> dict:
    """Nessie occasionally answers a seed deposit with a transient 500. One failed deposit used to abort
    the whole persona (and the engagement with it); retry a few times with a short backoff instead."""
    for attempt in range(tries):
        try:
            return await proxy.deposit(token, account_id, amount_cents, desc)
        except httpx.HTTPStatusError as e:
            if e.response.status_code < 500 or attempt == tries - 1:
                raise
            print(f"[personas] seed deposit got {e.response.status_code} from Nessie; retrying ({attempt + 1}/{tries - 1})")
            await asyncio.sleep(1.0 + attempt)


def _acct_id(a: dict) -> str:
    return a.get("id") or a.get("_id")
