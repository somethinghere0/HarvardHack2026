"""Orchestrator API. Ties together: engagement/persona lifecycle, the Nessie webhook receiver and
event timeline, the indicator engine, OTP email delivery (called by the proxy), and the decoy-agent
runner. nginx serves this under /api/, so browser paths like /api/engagements arrive here as
/engagements. Proxy->orchestrator internal calls hit /internal/* directly."""
from __future__ import annotations

import asyncio
import secrets

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from . import classifier, db, daytona_runner, indicators, personas, responder
from .config import settings
from .gmail_client import Gmail
from .nessie import NessieAdmin

s = settings()
app = FastAPI(title="Honeybank orchestrator")
gmail = Gmail(s)


def _is_public(url: str) -> bool:
    """A URL a remote service (real Nessie) could actually reach — i.e. not localhost."""
    return bool(url) and not any(h in url for h in ("localhost", "127.0.0.1", "::1", "0.0.0.0"))


@app.on_event("startup")
async def startup():
    db.init_db(s.db_path)
    s.require("nessie_api_key")
    app.state.webhook_id = None
    app.state.webhook_secret = ""
    app.state.poller = None
    app.state.nessie = NessieAdmin(s.nessie_base_url, s.nessie_api_key)

    # A public (tunnel) URL lets Nessie push webhooks here; otherwise poll the /events feed.
    if s.public_url and _is_public(s.public_url):
        try:
            wh = await app.state.nessie.create_webhook(
                f"{s.public_url}/api/webhooks/nessie",
                events=["transaction.completed", "transfer.created", "account.balance_changed"])
            app.state.webhook_id = wh.get("id")
            app.state.webhook_secret = wh.get("secret", "")
            print(f"[orchestrator] webhook registered -> {s.public_url}/api/webhooks/nessie")
            return
        except Exception as e:
            print(f"[orchestrator] webhook registration failed ({e}); falling back to polling")
    app.state.poller = asyncio.create_task(_poll_events())
    print("[orchestrator] polling GET /events for money-movement")


@app.on_event("shutdown")
async def shutdown():
    if app.state.poller:
        app.state.poller.cancel()
    if app.state.nessie:
        if app.state.webhook_id:
            await app.state.nessie.delete_webhook(app.state.webhook_id)
        await app.state.nessie.aclose()


async def _poll_events(interval: float = 2.0):
    """Resume Nessie's /events feed from its cursor and ingest money-movement events the same way the
    webhook receiver does. Starts at the current tip so it doesn't replay the whole tenant history."""
    cursor = None
    try:
        _, cursor = await app.state.nessie.get_events(limit=1)
    except Exception:
        pass
    while True:
        try:
            items, nxt = await app.state.nessie.get_events(after=cursor, limit=200)
            for ev in items:
                _ingest_nessie_event(ev)
            if nxt is not None:
                cursor = nxt
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[orchestrator] events poll error: {e}")
        await asyncio.sleep(interval)


# Dedupe ingested events by their Nessie id, so webhook retries or a replayed cursor can't
# double-count a transfer (which would spam the timeline and inflate indicators).
_seen_events: set = set()


def _ingest_nessie_event(env: dict) -> None:
    """Map a Nessie v2 event envelope onto the timeline. Real shape:
    {id, seq, type:'transaction.*', account_id, data:{transaction:{kind, amount_cents, payer_id,
    payee_id, status}}}. Normalizes to '<kind>.<status/created>' so the indicator engine reads it."""
    # Dedupe by transaction id when present, so the created + settled events for one transaction
    # (different event ids, same tx_id) are counted once.
    ev_id = env.get("tx_id") or env.get("id") or env.get("seq")
    if ev_id is not None:
        if ev_id in _seen_events:
            return
        _seen_events.add(ev_id)
        if len(_seen_events) > 10000:
            _seen_events.clear()
    data = env.get("data", env) or {}
    txn = data.get("transaction", data)
    kind = (txn.get("kind") or "").lower()
    account_id = env.get("account_id") or txn.get("payer_id") or txn.get("payee_id")
    eid = None
    for cand in (account_id, txn.get("payer_id"), txn.get("payee_id")):
        eid = eid or (db.find_engagement_by_account(s.db_path, cand) if cand else None)
    if not eid:
        return
    etype = f"{kind}.created" if kind in ("transfer", "deposit", "withdrawal") else env.get("type", "event")
    db.add_event(s.db_path, eid, "nessie", etype, {
        "account_id": account_id, "kind": kind, "status": txn.get("status"),
        "amount_cents": txn.get("amount_cents"), "payer_id": txn.get("payer_id"),
        "payee_id": txn.get("payee_id"), "description": txn.get("description", ""),
    })
    indicators.recompute_and_store(s.db_path, eid)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    """Which integrations are configured — powers the dashboard's setup strip. 'missing' means the
    feature can't run until its key/URL is set."""
    on = lambda ok, label="live": label if ok else "missing"  # noqa: E731
    return {"services": {
        "nessie": on(bool(s.nessie_api_key)),
        "gmail": gmail.mode if (s.gmail_app_password or s.gmail_address) else "missing",
        "daytona": on(bool(s.daytona_api_key)),
        "anthropic": on(bool(s.anthropic_api_key)),
        "webhooks": "live" if (s.public_url and _is_public(s.public_url)) else "polling",
    }, "public_url": s.public_url or None}


# --- public / dashboard API ------------------------------------------------

@app.get("/engagements")
def list_engagements():
    return {"engagements": db.list_engagements(s.db_path)}


@app.get("/engagements/{eid}")
def get_engagement(eid: str):
    eng = db.get_engagement(s.db_path, eid)
    if not eng:
        raise HTTPException(404, "engagement not found")
    return {
        "engagement": eng,
        "events": db.list_events(s.db_path, eid),
        "emails": db.list_emails(s.db_path, eid),
        "shots": db.list_shots(s.db_path, eid),
        "indicators": indicators.compute(s.db_path, eid),
    }


@app.post("/engagements", status_code=201)
async def create_engagement(body: dict):
    """Open an engagement and build its decoy persona. Body: {scammer_email?, subject?, channel?}."""
    eid = secrets.token_hex(8)
    db.create_engagement(s.db_path, eid, body.get("channel", "email"),
                         body.get("scammer_email"), body.get("subject"))
    persona = await personas.create_persona(s, eid)
    db.update_engagement(s.db_path, eid, status="baited")
    return {"engagement_id": eid, "persona": _safe_persona(persona)}


@app.post("/engagements/{eid}/run-agent")
async def run_agent(eid: str, background: BackgroundTasks):
    if not db.get_engagement(s.db_path, eid):
        raise HTTPException(404, "engagement not found")
    background.add_task(_run_agent_task, eid)
    return {"status": "started", "engagement_id": eid}


async def _run_agent_task(eid: str):
    try:
        await daytona_runner.run(s, eid)
    except Exception as e:
        db.add_event(s.db_path, eid, "system", "agent.error", {"error": str(e)})


# --- email firewall: vet every inbound email -------------------------------

async def vet_email(sender: str, subject: str, text: str, gmail_id: str | None = None) -> dict:
    """The core: classify one inbound email, record it on the dashboard, and for a credential-phishing
    scam spin up a honeypot engagement (decoy persona + reply + sandbox agent). Returns the verdict
    and the action the mail client should take: deliver (safe) or quarantine (scam)."""
    if gmail_id and db.message_seen(s.db_path, gmail_id):
        return {"already_processed": True}
    verdict = classifier.classify(s, sender, subject, text)
    is_scam = bool(verdict.get("is_scam"))
    action = "quarantined" if is_scam else "delivered"
    eid = None
    if is_scam:
        eid = secrets.token_hex(8)
        db.create_engagement(s.db_path, eid, "email", sender, subject)
        db.add_email(s.db_path, eid, "in", "scam", sender, s.gmail_address, subject, text)
        db.add_event(s.db_path, eid, "gmail", "email.scam_detected", verdict)
        if verdict.get("portal_url"):
            db.add_event(s.db_path, eid, "gmail", "portal.detected", {"url": verdict["portal_url"]})
        # Only credential-phishing is worth the full decoy-login honeypot; other scams are quarantined
        # and shown, without burning a sandbox.
        if verdict.get("vector") == "credential_phishing":
            persona = await personas.create_persona(s, eid)
            reply = responder.draft_reply(s, verdict.get("vector"),
                                          {"first_name": persona_firstname(persona)}, f"{subject}\n{text}")
            try:
                gmail.send(sender, f"Re: {subject}", reply)
                db.add_email(s.db_path, eid, "out", "reply", persona["email"], sender, f"Re: {subject}", reply)
                db.add_event(s.db_path, eid, "agent", "reply.sent", {"vector": verdict.get("vector")})
            except Exception as e:
                db.add_event(s.db_path, eid, "agent", "reply.failed", {"error": str(e)})
            asyncio.create_task(_run_agent_task(eid))
        db.update_engagement(s.db_path, eid, status="baited",
                             summary=f"{verdict.get('vector')} ({int(verdict.get('confidence', 0) * 100)}% conf.)")
    db.add_message(s.db_path, {
        "gmail_id": gmail_id, "sender": sender, "subject": subject, "body": text,
        "verdict": "scam" if is_scam else "safe", "vector": verdict.get("vector"),
        "confidence": verdict.get("confidence"), "reason": verdict.get("reason"),
        "action": action, "engagement_id": eid,
    })
    return {"verdict": "scam" if is_scam else "safe", "action": action,
            "engagement_id": eid, "classification": verdict}


@app.post("/ingest-email")
async def ingest_email(body: dict):
    """Vet one real inbound email (called by the Gmail watcher). Body: {gmail_id, sender, subject, body}."""
    return await vet_email(body.get("sender", ""), body.get("subject", ""),
                           body.get("body", ""), body.get("gmail_id"))


@app.get("/messages")
def list_messages():
    """Every email the firewall has vetted, newest first — safe (delivered) and scam (quarantined)."""
    return {"messages": db.list_messages(s.db_path)}


# --- simulation endpoints (manual triggers for the demo) -------------------

@app.post("/sim/inbound-email")
async def sim_inbound_email(body: dict):
    return await vet_email(body.get("sender", ""), body.get("subject", ""), body.get("body", ""))


@app.post("/sim/run-full")
async def sim_run_full(body: dict):
    """One-click demo: inject a credential-phishing email -> engagement -> decoy agent runs."""
    return await vet_email(
        (body or {}).get("sender", "alerts@secure-verify.example"),
        (body or {}).get("subject", "Unusual activity on your account"),
        (body or {}).get("body", "We detected unusual activity. Verify your login now at the link."))


# --- internal API (called by the proxy; shared-secret guarded) -------------

def _check_internal(secret: str | None):
    if secret != s.internal_secret:
        raise HTTPException(401, "bad internal secret")


@app.post("/internal/send-otp")
async def internal_send_otp(body: dict, x_internal_secret: str = Header(None)):
    _check_internal(x_internal_secret)
    username, challenge_id, code = body["username"], body["challenge_id"], body["code"]
    persona = db.get_persona_by_username(s.db_path, username)
    if not persona:
        raise HTTPException(404, "no persona for user")
    from datetime import datetime, timedelta, timezone
    expires = (datetime.now(timezone.utc) + timedelta(seconds=s.otp_ttl_seconds)).isoformat()
    db.create_otp(s.db_path, challenge_id, persona["id"], code, expires)
    # Email the persona inbox (best-effort — the agent reads the code from /internal/otp regardless).
    subject = "Your Honeybank verification code"
    text = f"Your Honeybank verification code is {code}. It expires in {s.otp_ttl_seconds // 60} minutes."
    emailed = False
    try:
        gmail.send(persona["email"], subject, text)
        db.add_email(s.db_path, persona["engagement_id"], "out", "otp", s.gmail_address,
                     persona["email"], subject, text)
        emailed = True
    except Exception as e:
        print(f"[orchestrator] OTP email failed ({e}); code still retrievable via /internal/otp")
    db.add_event(s.db_path, persona["engagement_id"], "system", "otp.sent",
                 {"emailed": emailed, "to": persona["email"]})
    return {"ok": True}


@app.post("/internal/agent-shot")
async def internal_agent_shot(body: dict, x_internal_secret: str = Header(None)):
    """A screenshot from the sandbox agent's browser — the fraud monitor shows these as a filmstrip."""
    _check_internal(x_internal_secret)
    eid = body.get("engagement_id")
    if eid and body.get("image"):
        db.add_shot(s.db_path, eid, int(body.get("step", 0)), body.get("label"), body["image"])
    return {"ok": True}


@app.get("/internal/otp/{persona_id}")
def internal_get_otp(persona_id: str, x_internal_secret: str = Header(None)):
    """The decoy agent's "inbox": the latest unconsumed OTP for its persona. Consumed on read."""
    _check_internal(x_internal_secret)
    otp = db.latest_otp_for_persona(s.db_path, persona_id)
    if not otp:
        raise HTTPException(404, "no code yet")
    db.consume_otp(s.db_path, otp["challenge_id"])
    return {"code": otp["code"]}


@app.post("/internal/event")
async def internal_event(body: dict, x_internal_secret: str = Header(None)):
    _check_internal(x_internal_secret)
    username = body.get("username")
    persona = db.get_persona_by_username(s.db_path, username) if username else None
    eid = persona["engagement_id"] if persona else body.get("engagement_id")
    if not eid:
        return {"ok": False}
    db.add_event(s.db_path, eid, body.get("source", "proxy"), body["type"], body.get("data", {}))
    indicators.recompute_and_store(s.db_path, eid)
    return {"ok": True}


@app.post("/internal/proxy-log")
async def internal_proxy_log(body: dict, x_internal_secret: str = Header(None)):
    _check_internal(x_internal_secret)
    acct = body.get("account_id")
    eid = db.find_engagement_by_account(s.db_path, acct) if acct else None
    if not eid and body.get("customer_id"):
        p = _persona_by_customer(body["customer_id"])
        eid = p["engagement_id"] if p else None
    if eid:
        db.add_event(s.db_path, eid, "proxy", "request",
                     {k: body.get(k) for k in ("method", "path", "status", "ip", "ua")})
    return {"ok": True}


# --- Nessie webhook receiver -----------------------------------------------

@app.post("/webhooks/nessie")
async def nessie_webhook(request: Request):
    raw = await request.body()
    secret = getattr(app.state, "webhook_secret", "")
    # Best-effort signature check: Nessie's exact signing header/algorithm isn't documented, so a
    # mismatch is logged rather than rejected — better to record the event than to silently drop a
    # real scammer's transfer over a format guess. The fake upstream signs with X-Nessie-Signature.
    if secret:
        import hashlib
        import hmac
        sig = request.headers.get("X-Nessie-Signature", "")
        if sig and not hmac.compare_digest(sig, hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()):
            print("[orchestrator] webhook signature mismatch (ingesting anyway)")
    import json as _json
    _ingest_nessie_event(_json.loads(raw or b"{}"))
    return {"ok": True}


# --- helpers ---------------------------------------------------------------

def _safe_persona(p: dict) -> dict:
    # The decoy credentials are intentionally returned here: this API is server-side/dashboard only.
    return p


def persona_firstname(persona: dict) -> str:
    row = db.get_persona(s.db_path, persona["persona_id"])
    return (row or {}).get("first_name", "")


def _persona_by_customer(customer_id: str) -> dict | None:
    for eng in db.list_engagements(s.db_path):
        for ev in db.list_events(s.db_path, eng["id"]):
            if ev["type"] == "persona.created" and ev["data"].get("customer_id") == customer_id:
                return db.get_persona(s.db_path, ev["data"]["persona_id"])
    return None
