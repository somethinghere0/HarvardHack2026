"""Runs the per-engagement decoy agent.

Real mode (DAYTONA_FAKE=0): spin up a disposable Daytona sandbox, run the browser agent that opens
the scammer's portal, submits the decoy credentials, and relays the OTP — every scammer gets a
throwaway victim machine. That browser-automation script is environment-specific and left as a
clearly marked scaffold below.

Fake mode (default): no sandbox. A local engine reproduces what the adversary does *to the decoy
bank* — logging in with the captured credentials (clearing the OTP step) and draining the decoy
accounts to a mule account — by driving the real proxy/Nessie path. This produces a genuine event
timeline and indicators for the dashboard, with no real money and no external calls."""
from __future__ import annotations

import asyncio
import random

from . import db, indicators
from .identity import generate_identity
from .proxy_client import ProxyClient


async def run(s, engagement_id: str) -> dict:
    if s.daytona_fake or not s.daytona_api_key:
        return await simulate_adversary(s, engagement_id)
    return await _run_in_sandbox(s, engagement_id)


# --- fake-mode engine: the demo's money-movement timeline -------------------

async def _ensure_mule(s, proxy: ProxyClient) -> str:
    """A separate Nessie account that stands in for the scammer's cash-out (mule) account."""
    ident = await generate_identity(s)
    import secrets
    res = await proxy.signup({
        "username": f"cashout_{secrets.token_hex(3)}", "password": secrets.token_urlsafe(12),
        "first_name": ident["first_name"], "last_name": ident["last_name"], "address": ident["address"],
    })
    acct = await proxy.open_account(res["token"], res["customer_id"],
                                    {"type": "Checking", "nickname": "External", "balance_cents": 0})
    return acct.get("id") or acct.get("_id")


async def simulate_adversary(s, engagement_id: str) -> dict:
    persona = _require_persona(s, engagement_id)
    proxy = ProxyClient(s.proxy_url)

    # 1. Log in with the captured credentials, clearing the OTP step (code read from our own store,
    #    exactly as the real agent would read it from the persona's inbox).
    login = await proxy.login(persona["username"], persona["password"])
    token = login.get("token")
    if login.get("otp_required"):
        code = await _await_otp(s, persona["id"])
        verified = await proxy.verify_otp(login["challenge_id"], code)
        token = verified["token"]
    db.add_event(s.db_path, engagement_id, "agent", "session.login",
                 {"username": persona["username"], "via": "decoy-agent", "otp_cleared": bool(login.get("otp_required"))})

    # 2. Add the mule payee, then drain. Mix of sub-threshold transfers (structuring) + a big sweep.
    mule = await _ensure_mule(s, proxy)
    db.add_event(s.db_path, engagement_id, "agent", "payee.added", {"payee_id": mule, "label": "external"})
    accounts = await proxy.accounts(token, persona["customer_id"])
    moved = 0
    for acct in accounts:
        bal = int(acct.get("balance_cents") or 0)
        aid = acct.get("id") or acct.get("_id")
        if bal <= 0:
            continue
        chunks = _drain_plan(bal)
        for amt in chunks:
            await proxy.transfer(token, aid, mule, amt, "transfer")
            moved += amt
            await asyncio.sleep(0.05)

    result = indicators.recompute_and_store(s.db_path, engagement_id)
    db.add_event(s.db_path, engagement_id, "agent", "engagement.drained",
                 {"mule_account": mule, "moved_cents": moved, "risk_score": result["risk_score"]})
    db.update_engagement(s.db_path, engagement_id, status="drained",
                         summary=f"Drained ${moved/100:,.2f} to mule account {mule[-6:]}.")
    return {"mule_account": mule, "moved_cents": moved, **result}


def _drain_plan(balance_cents: int) -> list[int]:
    """A few structuring-style sub-$1,000 transfers, then sweep the rest — a common laundering shape."""
    plan, remaining = [], balance_cents
    for _ in range(random.randint(2, 3)):
        if remaining <= 0:
            break
        amt = min(remaining, random.randint(60000, 99000))
        plan.append(amt)
        remaining -= amt
    if remaining > 0:
        plan.append(remaining)
    return plan


async def _await_otp(s, persona_id: str, tries: int = 50) -> str:
    for _ in range(tries):
        otp = db.latest_otp_for_persona(s.db_path, persona_id)
        if otp:
            return otp["code"]
        await asyncio.sleep(0.1)
    raise RuntimeError("OTP never arrived for persona")


def _require_persona(s, engagement_id: str) -> dict:
    for e in db.list_events(s.db_path, engagement_id):
        if e["type"] == "persona.created":
            p = db.get_persona(s.db_path, e["data"]["persona_id"])
            if p:
                return p
    raise RuntimeError("engagement has no persona yet")


# --- real-mode scaffold -----------------------------------------------------

async def _run_in_sandbox(s, engagement_id: str) -> dict:
    """Create a disposable sandbox and run the browser agent inside it. The agent script that drives
    the scammer's portal (Playwright + an LLM loop, reading the OTP from the persona inbox) is
    deployment-specific; wire it where marked. Falls back to the local engine if Daytona is
    unavailable so a live demo never hard-fails."""
    try:
        from daytona import Daytona, DaytonaConfig  # lazy import
    except Exception:
        db.add_event(s.db_path, engagement_id, "system", "daytona.unavailable",
                     {"note": "SDK missing; using local engine"})
        return await simulate_adversary(s, engagement_id)

    cfg = DaytonaConfig(api_key=s.daytona_api_key, api_url=s.daytona_api_url or None,
                        target=s.daytona_target or None)
    daytona = Daytona(cfg)
    sandbox = daytona.create()
    try:
        db.add_event(s.db_path, engagement_id, "system", "sandbox.created", {"sandbox_id": getattr(sandbox, "id", None)})
        # TODO: upload + run the browser agent in `sandbox` (sandbox.process.exec / code_run),
        # passing engagement_id, persona creds, the scammer portal URL, and ORCHESTRATOR_URL so it
        # can report events back. For now, drive the decoy bank locally to produce the timeline.
        return await simulate_adversary(s, engagement_id)
    finally:
        try:
            sandbox.delete()
        except Exception:
            pass
