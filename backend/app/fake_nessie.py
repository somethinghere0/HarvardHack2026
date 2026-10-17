"""A bundled, in-memory stand-in for the Nessie v2 API, used in FAKE mode so the whole system runs
with no key and no network. It mirrors the real v2 surface the app touches (cents amounts, the
/events feed, and notify webhooks), so the proxy and orchestrator run their real code paths against
it. Run it with: uvicorn app.fake_nessie:app  (dev.py does this for you). Nothing here is real."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, Request

app = FastAPI(title="Fake Nessie v2 (demo upstream)")

customers: dict[str, dict] = {}
accounts: dict[str, dict] = {}
events: list[dict] = []
webhooks: dict[str, dict] = {}
_seq = 0


def _id() -> str:
    return secrets.token_hex(12)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _acctnum() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(16))


async def _emit(type_: str, account_id: str, data: dict) -> None:
    global _seq
    _seq += 1
    env = {"seq": _seq, "id": _id(), "type": type_, "account_id": account_id,
           "data": data, "timestamp": _now()}
    events.append(env)
    # Deliver to every notify webhook whose event filter matches (empty filter = all).
    async with httpx.AsyncClient(timeout=10) as client:
        for wh in list(webhooks.values()):
            if wh["events"] and type_ not in wh["events"]:
                continue
            body = json.dumps(env).encode()
            headers = {"Content-Type": "application/json"}
            if wh.get("secret"):
                headers["X-Nessie-Signature"] = hmac.new(wh["secret"].encode(), body, hashlib.sha256).hexdigest()
            try:
                await client.post(wh["url"], content=body, headers=headers)
            except httpx.HTTPError:
                pass  # best effort, like a real webhook


@app.get("/health")
def health():
    return {"status": "ok", "fake": True}


@app.post("/customers", status_code=201)
async def create_customer(req: Request):
    b = await req.json()
    c = {"id": _id(), "first_name": b.get("first_name"), "last_name": b.get("last_name"),
         "address": b.get("address")}
    customers[c["id"]] = c
    return c


@app.get("/customers/{cid}")
def get_customer(cid: str):
    if cid not in customers:
        raise HTTPException(404, "customer not found")
    return customers[cid]


@app.get("/customers/{cid}/accounts")
def list_customer_accounts(cid: str):
    return [a for a in accounts.values() if a["customer_id"] == cid]


@app.post("/customers/{cid}/accounts", status_code=201)
async def open_account(cid: str, req: Request):
    if cid not in customers:
        raise HTTPException(404, "customer not found")
    b = await req.json()
    a = {"id": _id(), "customer_id": cid, "type": b.get("type", "Checking"),
         "nickname": b.get("nickname", "Account"), "balance_cents": int(b.get("balance_cents", 0)),
         "rewards": int(b.get("rewards", 0)), "account_number": _acctnum(),
         "credit_limit_cents": int(b.get("credit_limit_cents", 100000))}
    accounts[a["id"]] = a
    return a


@app.get("/accounts/{aid}")
def get_account(aid: str):
    if aid not in accounts:
        raise HTTPException(404, "account not found")
    return accounts[aid]


@app.get("/accounts/{aid}/customer")
def account_customer(aid: str):
    if aid not in accounts:
        raise HTTPException(404, "account not found")
    return customers[accounts[aid]["customer_id"]]


def _txns_for(aid: str, kind: str) -> list[dict]:
    out = []
    for e in events:
        if e["type"].split(".")[0] != kind:
            continue
        d = e["data"]
        if d.get("payer_id") == aid or d.get("payee_id") == aid or e["account_id"] == aid:
            out.append({"id": e["id"], "status": "executed", "transaction_date": e["timestamp"][:10],
                        "amount_cents": d.get("amount_cents"), "description": d.get("description", ""),
                        "payer_id": d.get("payer_id"), "payee_id": d.get("payee_id")})
    return out


@app.get("/accounts/{aid}/transfers")
def get_transfers(aid: str):
    return _txns_for(aid, "transfer")


@app.get("/accounts/{aid}/deposits")
def get_deposits(aid: str):
    return _txns_for(aid, "deposit")


@app.get("/accounts/{aid}/withdrawals")
def get_withdrawals(aid: str):
    return _txns_for(aid, "withdrawal")


@app.get("/accounts/{aid}/transactions")
def get_transactions(aid: str):
    return _txns_for(aid, "transfer") + _txns_for(aid, "deposit") + _txns_for(aid, "withdrawal")


@app.post("/accounts/{aid}/deposits", status_code=201)
async def deposit(aid: str, req: Request):
    if aid not in accounts:
        raise HTTPException(404, "account not found")
    b = await req.json()
    amt = int(b.get("amount_cents", 0))
    if amt <= 0:
        raise HTTPException(422, "amount_cents must be positive")
    accounts[aid]["balance_cents"] += amt
    data = {"payee_id": aid, "amount_cents": amt, "description": b.get("description", "")}
    await _emit("deposit.created", aid, data)
    await _emit("transaction.completed", aid, {**data, "kind": "deposit"})
    await _emit("account.balance_changed", aid, {"balance_cents": accounts[aid]["balance_cents"]})
    return {"id": _id(), "status": "executed", **data}


@app.post("/accounts/{aid}/transfers", status_code=201)
async def transfer(aid: str, req: Request):
    if aid not in accounts:
        raise HTTPException(404, "source account not found")
    b = await req.json()
    payee = b.get("payee_id")
    if payee not in accounts:
        raise HTTPException(404, "payee account not found")
    amt = int(b.get("amount_cents", 0))
    if amt <= 0:
        raise HTTPException(422, "amount_cents must be positive")
    accounts[aid]["balance_cents"] -= amt
    accounts[payee]["balance_cents"] += amt
    data = {"payer_id": aid, "payee_id": payee, "amount_cents": amt, "description": b.get("description", "")}
    await _emit("transfer.created", aid, data)
    await _emit("transaction.completed", aid, {**data, "kind": "transfer"})
    await _emit("account.balance_changed", aid, {"balance_cents": accounts[aid]["balance_cents"]})
    return {"id": _id(), "status": "executed", **data}


@app.post("/accounts/{aid}/withdrawals", status_code=201)
async def withdrawal(aid: str, req: Request):
    if aid not in accounts:
        raise HTTPException(404, "account not found")
    b = await req.json()
    amt = int(b.get("amount_cents", 0))
    accounts[aid]["balance_cents"] -= amt
    data = {"payer_id": aid, "amount_cents": amt, "description": b.get("description", "")}
    await _emit("withdrawal.created", aid, data)
    await _emit("transaction.completed", aid, {**data, "kind": "withdrawal"})
    return {"id": _id(), "status": "executed", **data}


@app.get("/events")
def get_events(after: int = 0, limit: int = 200):
    return [e for e in events if e["seq"] > int(after)][:limit]


@app.post("/webhooks", status_code=201)
async def create_webhook(req: Request):
    b = await req.json()
    wid = _id()
    webhooks[wid] = {"id": wid, "mode": b.get("mode", "notify"), "url": b["url"],
                     "events": b.get("events", []), "secret": secrets.token_hex(16)}
    return webhooks[wid]


@app.post("/webhooks/{wid}/ping")
async def ping_webhook(wid: str):
    if wid not in webhooks:
        raise HTTPException(404, "webhook not found")
    await _emit("webhook.ping", "", {"webhook_id": wid})
    return {"ok": True}


@app.delete("/webhooks/{wid}", status_code=204)
def delete_webhook(wid: str):
    webhooks.pop(wid, None)
