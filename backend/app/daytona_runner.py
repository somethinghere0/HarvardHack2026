"""Launches the decoy agent in a disposable Daytona sandbox. The scam email lures the victim to
Honeybank's own sign-in page, so the agent drives Honeybank directly: it signs in with the decoy
credentials, clears the OTP, and transfers the funds out to a mule account — all through the real
bank UI (backed by Nessie). Requires DAYTONA_API_KEY, ANTHROPIC_API_KEY, and a public PUBLIC_URL."""
from __future__ import annotations

import asyncio
import base64
import os
import secrets

from . import db
from .identity import generate_identity
from .proxy_client import ProxyClient

_AGENT_PATH = os.path.join(os.path.dirname(__file__), "..", "agent", "bank_agent.py")


async def run(s, engagement_id: str) -> dict:
    s.require("daytona_api_key", "anthropic_api_key", "public_url")
    persona = _require_persona(s, engagement_id)
    bank_url = s.public_url.rstrip("/") + "/"
    mule = await _ensure_mule(s)
    db.add_event(s.db_path, engagement_id, "agent", "payee.added", {"payee_id": mule, "label": "external"})
    agent_env = {
        "BANK_URL": bank_url,
        "AGENT_USERNAME": persona["username"],
        "AGENT_PASSWORD": persona["password"],
        "MULE_ACCOUNT": mule,
        "PERSONA_ID": persona["id"],
        "ENGAGEMENT_ID": engagement_id,
        "ORCHESTRATOR_URL": f"{s.public_url}/api",
        "INTERNAL_SECRET": s.internal_secret,
        "ANTHROPIC_API_KEY": s.anthropic_api_key,
        "ANTHROPIC_MODEL": s.anthropic_model,
    }
    db.add_event(s.db_path, engagement_id, "system", "sandbox.launching", {"bank": bank_url})
    try:
        result = await asyncio.to_thread(_run_sandbox, s, agent_env)
        db.add_event(s.db_path, engagement_id, "system", "sandbox.finished",
                     {"stdout_tail": (result or "")[-500:]})
        return {"ok": True}
    except Exception as e:
        db.add_event(s.db_path, engagement_id, "system", "agent.error", {"error": str(e)})
        raise


async def _ensure_mule(s) -> str:
    """A separate Nessie account standing in for the scammer's cash-out (mule) account."""
    proxy = ProxyClient(s.proxy_url)
    ident = await generate_identity(s)
    res = await proxy.signup({
        "username": f"cashout_{secrets.token_hex(3)}", "password": secrets.token_urlsafe(12),
        "first_name": ident["first_name"], "last_name": ident["last_name"], "address": ident["address"],
    })
    acct = await proxy.open_account(res["token"], res["customer_id"],
                                    {"type": "Checking", "nickname": "External", "balance_cents": 0})
    return acct.get("id") or acct.get("_id")


def _run_sandbox(s, agent_env: dict) -> str:
    from daytona import Daytona, DaytonaConfig

    cfg = DaytonaConfig(api_key=s.daytona_api_key, api_url=s.daytona_api_url or None,
                        target=s.daytona_target or None)
    daytona = Daytona(cfg)
    sandbox = daytona.create()
    try:
        sandbox.process.exec(
            "pip install -q playwright anthropic httpx && python -m playwright install --with-deps chromium",
            timeout=900)
        with open(os.path.abspath(_AGENT_PATH), "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        sandbox.process.exec(
            f"python -c \"import base64,pathlib;pathlib.Path('/tmp/agent.py').write_bytes(base64.b64decode('{b64}'))\"",
            timeout=60)
        res = sandbox.process.exec("python /tmp/agent.py", env=agent_env, timeout=900)
        return getattr(res, "result", "") or ""
    finally:
        try:
            sandbox.delete()
        except Exception:
            pass


def _require_persona(s, engagement_id: str) -> dict:
    for e in db.list_events(s.db_path, engagement_id):
        if e["type"] == "persona.created":
            p = db.get_persona(s.db_path, e["data"]["persona_id"])
            if p:
                return p
    raise RuntimeError("engagement has no persona yet")
