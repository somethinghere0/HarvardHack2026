"""Launches the decoy agent in a disposable Daytona sandbox: installs Playwright + Chromium, uploads
the browser agent, runs it against the portal with the persona's decoy credentials, then deletes the
sandbox. Requires DAYTONA_API_KEY, ANTHROPIC_API_KEY, and a public PUBLIC_URL/PORTAL_URL (the remote
sandbox must be able to reach the portal and the orchestrator)."""
from __future__ import annotations

import asyncio
import base64
import os

from . import db

_AGENT_PATH = os.path.join(os.path.dirname(__file__), "..", "agent", "portal_agent.py")


async def run(s, engagement_id: str) -> dict:
    s.require("daytona_api_key", "anthropic_api_key", "public_url")
    persona = _require_persona(s, engagement_id)
    base_portal = _detected_portal(s, engagement_id) or s.portal_url or f"{s.public_url}/portal"
    sep = "&" if "?" in base_portal else "?"
    portal_url = f"{base_portal}{sep}e={engagement_id}"
    agent_env = {
        "PORTAL_URL": portal_url,
        "AGENT_USERNAME": persona["username"],
        "AGENT_PASSWORD": persona["password"],
        "PERSONA_ID": persona["id"],
        "ENGAGEMENT_ID": engagement_id,
        "ORCHESTRATOR_URL": f"{s.public_url}/api",
        "INTERNAL_SECRET": s.internal_secret,
        "ANTHROPIC_API_KEY": s.anthropic_api_key,
        "ANTHROPIC_MODEL": s.anthropic_model,
    }
    db.add_event(s.db_path, engagement_id, "system", "sandbox.launching", {"portal": portal_url})
    try:
        result = await asyncio.to_thread(_run_sandbox, s, agent_env)
        db.add_event(s.db_path, engagement_id, "system", "sandbox.finished",
                     {"stdout_tail": (result or "")[-500:]})
        return {"ok": True}
    except Exception as e:
        db.add_event(s.db_path, engagement_id, "system", "agent.error", {"error": str(e)})
        raise


def _run_sandbox(s, agent_env: dict) -> str:
    from daytona import Daytona, DaytonaConfig

    cfg = DaytonaConfig(api_key=s.daytona_api_key, api_url=s.daytona_api_url or None,
                        target=s.daytona_target or None)
    daytona = Daytona(cfg)
    sandbox = daytona.create()
    try:
        # 1. install the agent's runtime
        sandbox.process.exec(
            "pip install -q playwright anthropic httpx && python -m playwright install --with-deps chromium",
            timeout=900)
        # 2. upload the agent script (base64 to avoid quoting issues)
        with open(os.path.abspath(_AGENT_PATH), "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        sandbox.process.exec(
            f"python -c \"import base64,pathlib;pathlib.Path('/tmp/agent.py').write_bytes(base64.b64decode('{b64}'))\"",
            timeout=60)
        # 3. run it
        res = sandbox.process.exec("python /tmp/agent.py", env=agent_env, timeout=600)
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


def _detected_portal(s, engagement_id: str) -> str | None:
    for e in db.list_events(s.db_path, engagement_id):
        if e["type"] == "portal.detected":
            return e["data"].get("url")
    return None
