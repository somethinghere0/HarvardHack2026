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


@app.on_event("startup")
async def startup():
    db.init_db(s.db_path)
    app.state.nessie = NessieAdmin(s.nessie_base_url, s.nessie_api_key or "fake") \
        if (s.public_url or not s.nessie_fake) else None
    app.state.webhook_id = None
    if app.state.nessie and s.public_url:
        try:
            wh = await app.state.nessie.create_webhook(
                f"{s.public_url}/api/webhooks/nessie",
                events=["transaction.completed", "transfer.created", "account.balance_changed"])
            app.state.webhook_id = wh.get("id")
            app.state.webhook_secret = wh.get("secret", "")
        except Exception as e:  # tunnel/key not ready: fall back to no webhook (sim still works)
            app.state.webhook_secret = ""
            print(f"[orchestrator] webhook registration skipped: {e}")
    else:
        app.state.webhook_secret = ""


@app.on_event("shutdown")
async def shutdown():
    if app.state.nessie:
        if app.state.webhook_id:
            await app.state.nessie.delete_webhook(app.state.webhook_id)
        await app.state.nessie.aclose()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/status")
def status():
    """Which services are live vs. faked — powers the dashboard's setup strip."""
    def mode(is_fake: bool) -> str:
        return "fake" if is_fake else "live"
    return {"services": {
        "nessie": mode(s.nessie_fake),
        "gmail": mode(s.gmail_fake),
        "daytona": mode(s.daytona_fake),
        "photon": mode(s.photon_fake),
        "anthropic": "live" if s.anthropic_api_key else "fake",
        "webhooks": "live" if (s.public_url and not s.nessie_fake) else ("local" if s.public_url else "polling"),
    }, "otp_mode": s.otp_mode, "public_url": s.public_url or None}


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


# --- simulation endpoints (demo; local only) -------------------------------

@app.post("/sim/inbound-email")
async def sim_inbound_email(body: dict):
    """Simulate a scam email arriving. Body: {sender, subject, body}. Classifies, and if it looks
    like a scam, opens an engagement with a fresh persona and drafts a decoy reply."""
    sender, subject, text = body.get("sender", ""), body.get("subject", ""), body.get("body", "")
    verdict = classifier.classify(s, sender, subject, text)
    if not verdict.get("is_scam"):
        return {"opened": False, "classification": verdict}
    eid = secrets.token_hex(8)
    db.create_engagement(s.db_path, eid, "email", sender, subject)
    db.add_email(s.db_path, eid, "in", "scam", sender, s.gmail_address, subject, text)
    db.add_event(s.db_path, eid, "gmail", "email.scam_detected", verdict)
    persona = await personas.create_persona(s, eid)
    reply = responder.draft_reply(s, verdict.get("vector", "unknown"),
                                  {"first_name": persona_firstname(persona)}, f"{subject}\n{text}")
    gmail.send(sender, f"Re: {subject}", reply)
    db.add_email(s.db_path, eid, "out", "reply", persona["email"], sender, f"Re: {subject}", reply)
    db.add_event(s.db_path, eid, "agent", "reply.sent", {"vector": verdict.get("vector")})
    db.update_engagement(s.db_path, eid, status="baited",
                         summary=f"{verdict.get('vector')} ({int(verdict.get('confidence',0)*100)}% conf.)")
    return {"opened": True, "engagement_id": eid, "classification": verdict,
            "persona": _safe_persona(persona)}


@app.post("/sim/run-full")
async def sim_run_full(body: dict, background: BackgroundTasks):
    """One-click demo: inbound scam email -> engagement -> run the decoy agent (login + drain)."""
    res = await sim_inbound_email(body or {"sender": "alerts@secure-verify.example",
                                           "subject": "Unusual activity on your account",
                                           "body": "We detected unusual activity. Verify your login now."})
    if res.get("opened"):
        background.add_task(_run_agent_task, res["engagement_id"])
    return res


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
    if s.otp_mode == "email":
        subject = "Your Honeybank verification code"
        text = f"Your Honeybank verification code is {code}. It expires in {s.otp_ttl_seconds//60} minutes."
        gmail.send(persona["email"], subject, text)
        db.add_email(s.db_path, persona["engagement_id"], "out", "otp", s.gmail_address,
                     persona["email"], subject, text)
    db.add_event(s.db_path, persona["engagement_id"], "system", "otp.sent",
                 {"mode": s.otp_mode, "to": persona["email"]})
    return {"ok": True}


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
    env = await request.json()
    data = env.get("data", {})
    account_id = env.get("account_id") or data.get("payer_id") or data.get("payee_id")
    eid = db.find_engagement_by_account(s.db_path, account_id) if account_id else None
    if not eid:
        # Payee may be the mule (external); try payer explicitly.
        for cand in (data.get("payer_id"), data.get("payee_id")):
            eid = eid or (db.find_engagement_by_account(s.db_path, cand) if cand else None)
    if eid:
        db.add_event(s.db_path, eid, "nessie", env.get("type", "event"), {**data, "account_id": account_id})
        indicators.recompute_and_store(s.db_path, eid)
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
