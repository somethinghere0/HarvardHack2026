"""Orchestrator API. Ties together: engagement/persona lifecycle, the Nessie webhook receiver and
event timeline, the indicator engine, OTP email delivery (called by the proxy), and the decoy-agent
runner. nginx serves this under /api/, so browser paths like /api/engagements arrive here as
/engagements. Proxy->orchestrator internal calls hit /internal/* directly."""
from __future__ import annotations

import asyncio
import secrets

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

import re

from . import classifier, db, daytona_runner, indicators, outcome, personas, scam_lab
from .config import settings
from .gmail_client import Gmail
from .nessie import NessieAdmin, logged as nessie_logged

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
    app.state.nessie = nessie_logged(s, "system")

    # A public (tunnel) URL lets Nessie push webhooks here; otherwise poll the /events feed.
    if s.public_url and _is_public(s.public_url):
        try:
            wh = await app.state.nessie.create_webhook(
                f"{s.public_url}/api/webhooks/nessie",
                events=["transaction.created", "transaction.completed", "account.balance_changed"])
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
    env = env.get("event", env) if isinstance(env.get("event"), dict) else env
    # Balance-change events carry no transaction body (just kind + delta); the transaction.* event for
    # the same tx_id already records it, so ingesting these would add empty "deposit" rows.
    if env.get("type") == "account.balance_changed" or not isinstance((env.get("data") or {}).get("transaction"), dict):
        return
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
        "tx_id": env.get("tx_id") or txn.get("id"), "account_id": account_id, "kind": kind, "status": txn.get("status"),
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


# --- email firewall: detonate every inbound email --------------------------

_detonations: asyncio.Semaphore | None = None


async def vet_email(sender: str, subject: str, text: str, gmail_id: str | None = None) -> dict:
    """The core: every inbound email is held and detonated in a sandbox. A decoy victim does what
    the email asks; the verdict is whatever that cost the decoy (outcome.py). Returns at once with
    verdict 'pending' — the detonation runs in the background and the watcher picks up the result."""
    if gmail_id and db.message_seen(s.db_path, gmail_id):
        return {"already_processed": True}
    eid = secrets.token_hex(8)
    db.create_engagement(s.db_path, eid, "email", sender, subject)
    db.add_email(s.db_path, eid, "in", "inbound", sender, s.gmail_address, subject, text)
    db.update_engagement(s.db_path, eid, status="detonating")
    msg_id = db.add_message(s.db_path, {
        "gmail_id": gmail_id, "sender": sender, "subject": subject, "body": text,
        "verdict": "pending", "action": "held", "engagement_id": eid,
        "reason": "Detonating in a sandbox: a decoy victim is following the email's instructions.",
    })
    asyncio.create_task(_detonate(eid, msg_id, sender, subject, text))
    return {"verdict": "pending", "action": "held", "engagement_id": eid, "message_id": msg_id}


async def _detonate(eid: str, msg_id: int, sender: str, subject: str, text: str) -> None:
    global _detonations
    _detonations = _detonations or asyncio.Semaphore(max(1, s.max_detonations))
    async with _detonations:
        try:
            plan = await asyncio.to_thread(classifier.extract, s, sender, subject, text)
            db.add_event(s.db_path, eid, "gmail", "email.extracted", plan)
            link = (plan.get("links") or [None])[0] or _first_url(text)
            if link:
                db.add_event(s.db_path, eid, "gmail", "portal.detected", {"url": link})
            await personas.create_persona(s, eid)
            await daytona_runner.run(s, eid)
            # Transfers reach us through Nessie's webhook/poller a moment after the agent clicks Send.
            await asyncio.sleep(s.verdict_grace_seconds)
        except Exception as e:
            print(f"[orchestrator] detonation {eid} failed: {e}")
            db.add_event(s.db_path, eid, "system", "agent.error", {"error": str(e)[:300]})
        await _reconcile_outflows(eid)
        _record_verdict(eid, msg_id)


async def _reconcile_outflows(eid: str) -> int:
    """Read the decoy's accounts straight from Nessie and ingest any money that left them. Webhooks
    for transfers can lag or never arrive (deposits do), and a verdict decided on a missing event
    would call a drained account 'safe'. The ledger is the ground truth, so check it before judging."""
    own: list[str] = []
    for e in db.list_events(s.db_path, eid):
        if e["type"] == "persona.created":
            own.extend(e["data"].get("accounts") or [])
    if not own:
        return 0
    nessie = nessie_logged(s, eid)
    found = 0
    try:
        for acct in own:
            try:
                txns = await nessie.list_transactions(acct)
            except Exception as ex:
                print(f"[orchestrator] reconcile: couldn't read {acct}: {ex}")
                continue
            for txn in txns:
                if (txn.get("kind") or "").lower() not in ("transfer", "withdrawal") or txn.get("payer_id") != acct:
                    continue
                found += 1
                _ingest_nessie_event({"id": txn.get("id"), "tx_id": txn.get("id"), "type": "transaction.created",
                                      "account_id": acct, "data": {"transaction": txn}})
    finally:
        await nessie.aclose()
    if found:
        db.add_event(s.db_path, eid, "system", "ledger.reconciled",
                     {"outflows": found, "note": "read back from Nessie before the verdict"})
    return found


def _record_verdict(eid: str, msg_id: int) -> dict:
    v = outcome.decide(s.db_path, eid)
    action = {"scam": "quarantined", "safe": "delivered"}.get(v["verdict"], "review")
    db.add_event(s.db_path, eid, "system", "verdict", v)
    db.update_message(s.db_path, msg_id, verdict=v["verdict"], vector=v["vector"], reason=v["reason"],
                      action=action, confidence=1.0 if v["verdict"] != "error" else None)
    ind = indicators.recompute_and_store(s.db_path, eid)
    db.update_engagement(s.db_path, eid, summary=v["reason"][:300], status={
        "scam": "drained" if "full_drain" in ind["tags"] else "compromised",
        "safe": "cleared"}.get(v["verdict"], "inconclusive"))
    return v


@app.post("/engagements/{eid}/rejudge")
async def rejudge(eid: str):
    """Re-read the ledger and decide the verdict again — for a run whose transfer event arrived late."""
    if not db.get_engagement(s.db_path, eid):
        raise HTTPException(404, "engagement not found")
    msg = next((m for m in db.list_messages(s.db_path, 1000) if m.get("engagement_id") == eid), None)
    if not msg:
        raise HTTPException(404, "no inbox message for this engagement")
    await _reconcile_outflows(eid)
    return _record_verdict(eid, msg["id"])


@app.post("/ingest-email")
async def ingest_email(body: dict):
    """Detonate one real inbound email (called by the Gmail watcher). Body: {gmail_id, sender, subject, body}."""
    return await vet_email(body.get("sender", ""), body.get("subject", ""),
                           body.get("body", ""), body.get("gmail_id"))


@app.post("/verdicts")
def verdicts(body: dict):
    """Current verdict for each Gmail message id — the watcher polls this for emails still detonating."""
    return {"verdicts": {m["gmail_id"]: m for m in db.messages_by_gmail_ids(s.db_path, body.get("gmail_ids") or [])}}


@app.get("/messages")
def list_messages():
    """Every email the firewall has detonated, newest first — pending, safe, and scam."""
    return {"messages": db.list_messages(s.db_path)}


# --- simulation endpoints (manual triggers for the demo) -------------------

@app.post("/sim/inbound-email")
async def sim_inbound_email(body: dict):
    return await vet_email(body.get("sender", ""), body.get("subject", ""), body.get("body", ""))


@app.get("/sim/scam-email")
async def sim_scam_email():
    """A ready-to-send demo scam: a 'safe account' fraud that tells the victim to sign in and move
    their balance to a fresh scammer-held account. Paste it into a real email to the watched inbox."""
    mule = await daytona_runner.create_scammer_account(s)
    bank = (s.public_url or s.local_bank_url).rstrip("/") + "/"
    return {"mule_account": mule, "sender": "security@bankofusa-alerts.example",
            "subject": "URGENT: your Bank of USA account has been compromised",
            "body": (f"Our fraud team detected unauthorized access to your Bank of USA account. To protect "
                     f"your money, sign in now at {bank} and transfer your full available balance to our "
                     f"protected holding account {mule} while we secure your profile. Funds left in your "
                     f"account after 2 hours cannot be recovered.\n\nBank of USA Fraud Prevention")}


@app.get("/swarm/scenarios")
def swarm_scenarios():
    """The scam types Nessie can inject, each with a one-line description for the dashboard."""
    desc = {
        "account_takeover": "a new payee, then the account is drained",
        "large_transfer_new_payee": "one big transfer to someone never paid before",
        "card_testing": "bursts of tiny purchases, most never posting",
        "structuring": "repeated amounts just under a reporting threshold",
        "velocity_spike": "far more purchases than the account's usual pace",
        "foreign_atm_cashout": "a burst of withdrawals abroad, each with its fee",
        "geo_distant": "a purchase hundreds of miles from where they shop",
        "unusual_category": "a spend in a category their habits don't explain",
    }
    return {"scenarios": [{"id": k, "desc": desc.get(k, "")} for k in scam_lab.SCENARIOS]}


@app.post("/swarm/run")
async def swarm_run(body: dict, background: BackgroundTasks):
    """Kick off a swarm: one Nessie simulation per scam type, then one sandbox per customer case."""
    s.require("nessie_api_key")
    scenarios = body.get("scenarios") or scam_lab.SCENARIOS
    customers = max(1, min(int(body.get("customers", 40)), 200))
    anomaly_rate = float(body.get("anomaly_rate", 0.18))
    concurrency = max(1, min(int(body.get("concurrency", 8)), 64))
    use_claude = bool(body.get("use_claude", True))
    rid = "swarm_" + secrets.token_hex(5)
    db.create_swarm(s.db_path, rid, scenarios, customers, anomaly_rate)
    background.add_task(_swarm_task, rid, scenarios, customers, anomaly_rate, concurrency, use_claude)
    return {"run_id": rid, "scenarios": scenarios, "customers": customers}


async def _swarm_task(rid, scenarios, customers, anomaly_rate, concurrency, use_claude):
    try:
        await scam_lab.run_swarm(s, rid, scenarios, customers, anomaly_rate, concurrency, use_claude)
    except Exception as e:
        db.update_swarm(s.db_path, rid, status="error", totals={"error": str(e)})


@app.get("/swarm")
def swarm_list():
    return {"runs": db.list_swarms(s.db_path)}


@app.get("/swarm/{rid}")
def swarm_get(rid: str):
    run = db.get_swarm(s.db_path, rid)
    if not run:
        raise HTTPException(404, "no such swarm run")
    return {"run": run, "cases": db.list_cases(s.db_path, rid)}


@app.get("/swarm/{rid}/cases/{cid}")
def swarm_case(rid: str, cid: str):
    c = db.get_case(s.db_path, cid)
    if not c:
        raise HTTPException(404, "no such case")
    return {"case": c}


@app.post("/sim/run-full")
async def sim_run_full(body: dict):
    """One-click demo: send a 'safe account' scam through the full detonation pipeline."""
    body = body or {}
    mail = await sim_scam_email() if not body.get("body") else body
    return await vet_email(mail.get("sender", ""), mail.get("subject", ""), mail.get("body", ""))


@app.get("/engagements/{eid}/bank")
async def engagement_bank(eid: str):
    """Everything the decoy bank holds for this engagement, read live from Nessie: the persona's
    customer record, its accounts and their full transaction history, plus the mule account the
    money was moved to. The dashboard's data explorer renders this."""
    events = db.list_events(s.db_path, eid)
    created = next((e["data"] for e in events if e["type"] == "persona.created"), {})
    persona = db.get_persona(s.db_path, created["persona_id"]) if created.get("persona_id") else None
    own = set(created.get("accounts") or [])
    mule = next((e["data"].get("payee_id") for e in events if e["type"] == "transfer.created"
                 and e["data"].get("payer_id") in own and e["data"].get("payee_id") not in own), None)
    nessie = nessie_logged(s, eid)

    async def account(acct_id: str, role: str) -> dict:
        try:
            a, txs = await asyncio.gather(nessie.get_account(acct_id), nessie.list_transactions(acct_id))
        except Exception as e:
            return {"id": acct_id, "role": role, "error": str(e)}
        return {**a, "role": role, "transactions": txs}

    jobs = [account(a, "decoy") for a in created.get("accounts") or []]
    if mule:
        jobs.append(account(mule, "mule"))
    accounts = await asyncio.gather(*jobs)
    customer = None
    if created.get("customer_id"):
        try:
            customer = await nessie.get_customer(created["customer_id"])
        except Exception:
            customer = None
    await nessie.aclose()
    # Decoy credentials are intentionally shown: this API is dashboard-only and nothing here is real.
    return {"persona": persona, "customer": customer, "accounts": accounts}


@app.get("/nessie/calls")
def nessie_calls(scope: str | None = None, after: int = 0, limit: int = 200):
    """The Nessie API log: every request the stack made to Nessie, newest first."""
    return {"calls": db.list_nessie_calls(s.db_path, scope, after, min(limit, 1000)),
            "stats": db.nessie_call_stats(s.db_path, scope)}


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
    subject = "Your Bank of USA verification code"
    text = f"Your Bank of USA verification code is {code}. It expires in {s.otp_ttl_seconds // 60} minutes."
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


@app.post("/internal/nessie-call")
async def internal_nessie_call(body: dict, x_internal_secret: str = Header(None)):
    """The proxy's upstream Nessie calls (the bank site's traffic), attributed to an engagement by
    the customer/account id in the path."""
    _check_internal(x_internal_secret)
    path = body.get("path", "")
    scope = "proxy"
    for part in path.split("?")[0].split("/"):
        if part.startswith("acct_"):
            scope = db.find_engagement_by_account(s.db_path, part) or scope
        elif part.startswith("cust_"):
            p = _persona_by_customer(part)
            scope = p["engagement_id"] if p else scope
    db.add_nessie_call(s.db_path, scope, body.get("method", ""), path, body.get("status"), body.get("ms", 0),
                       body.get("request", ""), body.get("response", ""))
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


def _first_url(text: str) -> str:
    m = re.search(r"https?://[^\s<>\")]+", text or "")
    return m.group(0).rstrip(".,);]") if m else ""


def persona_firstname(persona: dict) -> str:
    row = db.get_persona(s.db_path, persona["persona_id"])
    return (row or {}).get("first_name", "")


def _persona_by_customer(customer_id: str) -> dict | None:
    for eng in db.list_engagements(s.db_path):
        for ev in db.list_events(s.db_path, eng["id"]):
            if ev["type"] == "persona.created" and ev["data"].get("customer_id") == customer_id:
                return db.get_persona(s.db_path, ev["data"]["persona_id"])
    return None
