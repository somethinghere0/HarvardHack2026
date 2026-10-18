"""Detonates one inbound email. A browser agent plays the recipient — a decoy Bank of USA customer
with a funded account, real credentials, and an inbox that receives its one-time codes — and does
exactly what the email asks: opens its links, signs in where told, enters codes, sends money where
told. The verdict then comes from what that cost the decoy (outcome.py), not from how the email reads.

Runtime (AGENT_RUNTIME): "daytona" runs it in a disposable Daytona sandbox, "local" runs it on this
machine, and "auto" (default) tries Daytona first. Daytona's Tier 1/2 sandboxes only reach an egress
allowlist (package registries, AI APIs) — not ngrok/cloudflared tunnels — so auto probes the sandbox's
route to PUBLIC_URL and falls back to a local run when it's blocked."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import platform
import secrets
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

from . import db
from .identity import generate_identity
from .nessie import NessieAdmin, logged as nessie_logged
from .proxy_client import ProxyClient

_AGENT_DIR = os.path.join(os.path.dirname(__file__), "..", "agent")
# AGENT_DRIVER selects the decoy brain: "dom" (default) scrapes the page and emits JSON actions
# (bank_agent.py); "computer_use" drives a real screen with Claude's computer toolset (cu_agent.py).
_DRIVER = os.environ.get("AGENT_DRIVER", "dom").strip().lower()
_AGENT_PATH = os.path.join(_AGENT_DIR, "cu_agent.py" if _DRIVER == "computer_use" else "bank_agent.py")


_TUNNEL_HOSTS = (".trycloudflare.com", ".ngrok-free.app", ".ngrok-free.dev", ".ngrok.app", ".ngrok.dev", ".ngrok.io")


async def run(s, engagement_id: str) -> dict:
    s.require("anthropic_api_key")
    runtime = s.agent_runtime
    if runtime == "daytona":
        s.require("daytona_api_key", "public_url")
    elif runtime == "auto" and not (s.daytona_api_key and s.public_url):
        runtime = "local"
    persona = _require_persona(s, engagement_id)
    mail = next((m for m in db.list_emails(s.db_path, engagement_id) if m["direction"] == "in"), None)
    if not mail:
        raise RuntimeError("engagement has no inbound email to detonate")
    base = (s.public_url or s.local_bank_url).rstrip("/")
    lure = _detected_link(s, engagement_id)
    await _wait_funded(s, engagement_id)
    email_blob = base64.b64encode(json.dumps(
        {"from": mail.get("sender") or "", "subject": mail.get("subject") or "", "body": mail.get("body") or ""}
    ).encode()).decode()
    agent_env = {
        "BANK_URL": base + "/",
        "START_URL": _start_url(base, lure),
        "EMAIL_B64": email_blob,
        "PERSONA_NAME": f"{persona.get('first_name', '')} {persona.get('last_name', '')}".strip(),
        "PERSONA_EMAIL": persona.get("email") or "",
        "AGENT_USERNAME": persona["username"],
        "AGENT_PASSWORD": persona["password"],
        "PERSONA_ID": persona["id"],
        "ENGAGEMENT_ID": engagement_id,
        "ORCHESTRATOR_URL": f"{s.public_url}/api",
        "PUBLIC_URL": s.public_url,
        "INTERNAL_SECRET": s.internal_secret,
        "ANTHROPIC_API_KEY": s.anthropic_api_key,
        "ANTHROPIC_MODEL": s.anthropic_model,
    }
    db.add_event(s.db_path, engagement_id, "system", "sandbox.launching",
                 {"bank": base + "/", "lure": lure, "runtime": runtime})
    try:
        emit = lambda type_, data: db.add_event(s.db_path, engagement_id, "system", type_, data)
        result = None
        if runtime in ("daytona", "auto"):
            result = await asyncio.to_thread(_run_sandbox, s, agent_env, emit, runtime == "auto")
            # The egress probe can pass and the tunnel still drop mid-run (it's intermittent on Daytona
            # Tier 1/2). An agent that never reported back can't be judged, so rerun it on the host.
            if result is not None and runtime == "auto" and not _has_event(s, engagement_id, "agent.started"):
                emit("sandbox.egress_blocked", {"public_url": s.public_url, "status": "lost mid-run"})
                result = None
        if result is None:  # local runtime, or Daytona can't reach the tunnel
            emit("runtime.local", {"host": platform.node(), "os": platform.platform(terse=True),
                                   "python": platform.python_version()})
            result = await asyncio.to_thread(_run_local, s, agent_env)
        tail = (result or "")[-500:]
        # A crash inside the sandbox can't always report back (e.g. the tunnel is down), so surface
        # the traceback's last line here — otherwise the monitor would wait on the browser forever.
        if "Traceback" in (result or "") and not _has_event(s, engagement_id, "agent.finished", "agent.error"):
            last = [l for l in tail.strip().splitlines() if l.strip() and not l.startswith(" ")]
            emit("agent.error", {"error": (last[-1] if last else "agent crashed")[:300]})
        emit("sandbox.finished", {"stdout_tail": tail})
        return {"ok": True}
    except Exception as e:
        db.add_event(s.db_path, engagement_id, "system", "agent.error", {"error": str(e)})
        raise


async def _wait_funded(s, engagement_id: str, timeout: float = 90) -> None:
    """Nessie holds new deposits pending for a while before they post. Start the agent only once the
    seeded history has landed — otherwise it signs in to $0.00 balances and has nothing to move."""
    created = next((e for e in db.list_events(s.db_path, engagement_id) if e["type"] == "persona.created"), None)
    accounts = (created or {}).get("data", {}).get("accounts") or []
    if not accounts:
        return
    db.add_event(s.db_path, engagement_id, "system", "persona.funding", {"accounts": accounts})
    admin = nessie_logged(s, engagement_id)
    total = 0
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            try:
                total = sum([(await admin.get_account(a)).get("balance_cents") or 0 for a in accounts])
            except Exception:
                total = 0
            if total > 0:
                break
            await asyncio.sleep(3)
    finally:
        await admin.aclose()
    db.add_event(s.db_path, engagement_id, "system", "persona.funded", {"balance_cents": total})


async def create_scammer_account(s) -> str:
    """A Nessie account standing in for a scammer's cash-out (mule) account — for writing demo scam
    emails that tell the victim to move money there."""
    proxy = ProxyClient(s.proxy_url)
    ident = await generate_identity(s)
    res = await proxy.signup({
        "username": f"cashout_{secrets.token_hex(3)}", "password": secrets.token_urlsafe(12),
        "first_name": ident["first_name"], "last_name": ident["last_name"], "address": ident["address"],
    })
    acct = await proxy.open_account(res["token"], res["customer_id"],
                                    {"type": "Checking", "nickname": "External", "balance_cents": 0})
    return acct.get("id") or acct.get("_id")


def _start_url(base: str, lure: str | None) -> str:
    """Where the victim's browser starts: the email's link, as-is. The one rewrite: a link to our own
    bank through an old tunnel hostname is moved onto the current address so it still resolves.
    No link => blank; the agent goes wherever the email's instructions say."""
    if not lure:
        return ""
    u, b = urlsplit(lure), urlsplit(base)
    host = (u.hostname or "").lower()
    if host == b.hostname or host.endswith(_TUNNEL_HOSTS) or host in ("localhost", "127.0.0.1"):
        return urlunsplit((b.scheme, b.netloc, u.path or "/", u.query, ""))
    return lure


def _run_local(s, agent_env: dict) -> str:
    env = {**os.environ, **agent_env, "ORCHESTRATOR_URL": s.local_url.rstrip("/"), "PYTHONUNBUFFERED": "1"}
    res = subprocess.run([sys.executable, os.path.abspath(_AGENT_PATH)], env=env,
                         capture_output=True, text=True, timeout=900)
    return (res.stdout or "") + (res.stderr or "")


def _run_sandbox(s, agent_env: dict, emit, fallback: bool) -> str | None:
    """Runs the agent in a Daytona sandbox. Returns None (sandbox discarded) when `fallback` is set and
    the sandbox can't reach PUBLIC_URL."""
    from daytona import Daytona, DaytonaConfig

    cfg = DaytonaConfig(api_key=s.daytona_api_key, api_url=s.daytona_api_url or None,
                        target=s.daytona_target or None)
    daytona = Daytona(cfg)
    sandbox = daytona.create()
    emit("sandbox.created", {"sandbox_id": getattr(sandbox, "id", ""),
                             **{k: str(getattr(sandbox, k)) for k in ("target", "cpu", "memory", "disk", "snapshot", "state")
                                if getattr(sandbox, k, None) not in (None, "")}})
    try:
        probe = sandbox.process.exec(
            f"curl -s -o /dev/null -m 10 -w '%{{http_code}}' -H 'ngrok-skip-browser-warning: 1' "
            f"{s.public_url}/api/health || true", timeout=30)
        code = (getattr(probe, "result", "") or "").strip()[-3:]
        if not code.startswith(("2", "3")):
            emit("sandbox.egress_blocked", {"public_url": s.public_url, "status": code or "000"})
            if fallback:
                return None
        emit("sandbox.installing", {})
        sandbox.process.exec(
            "pip install -q playwright anthropic httpx && python -m playwright install --with-deps chromium",
            timeout=900)
        with open(os.path.abspath(_AGENT_PATH), "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        sandbox.process.exec(
            f"python -c \"import base64,pathlib;pathlib.Path('/tmp/agent.py').write_bytes(base64.b64decode('{b64}'))\"",
            timeout=60)
        res = sandbox.process.exec("python /tmp/agent.py", env={**agent_env, "AGENT_IN_SANDBOX": "1"}, timeout=900)
        return getattr(res, "result", "") or ""
    finally:
        try:
            sandbox.delete()
        except Exception:
            pass


def _has_event(s, engagement_id: str, *types: str) -> bool:
    return any(e["type"] in types for e in db.list_events(s.db_path, engagement_id))


def _detected_link(s, engagement_id: str) -> str | None:
    for e in db.list_events(s.db_path, engagement_id):
        if e["type"] == "portal.detected":
            return e["data"].get("url")
    return None


def _require_persona(s, engagement_id: str) -> dict:
    for e in db.list_events(s.db_path, engagement_id):
        if e["type"] == "persona.created":
            p = db.get_persona(s.db_path, e["data"]["persona_id"])
            if p:
                return p
    raise RuntimeError("engagement has no persona yet")
