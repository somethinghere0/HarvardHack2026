from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .deps import require_user
from .nessie import response_headers

router = APIRouter(dependencies=[Depends(require_user)])

# Paths whose first segment is a shared/global collection a session may always read.
_GLOBAL = {"events", "atms", "branches", "merchants", "enums", "health"}
# Money-moving sub-resources under /accounts/{id}/… — each attempt is reported to the orchestrator
# with who made it, so the engagement's playbook can attribute every dollar to a session.
_MONEY = {"transfers": "transfer", "withdrawals": "withdrawal", "purchases": "purchase", "deposits": "deposit"}
_LIMITED = {"transfer", "withdrawal"}


async def _enforce_scope(request: Request, user, path: str) -> None:
    """Keep a session to its own customer's data so a logged-in scammer can't enumerate the other
    decoy customers. Transfers still reach any payee (the payee is in the body, not the path)."""
    if not request.app.state.settings.enforce_customer_scope:
        return
    seg = [p for p in path.split("/") if p]
    if not seg or seg[0].lower() in _GLOBAL:
        return
    head, customer = seg[0].lower(), user["nessie_customer_id"]
    if head == "customers":
        if len(seg) == 1 or seg[1] != customer:   # no listing all customers; only your own record
            raise HTTPException(403, "Not permitted")
    elif head == "accounts":
        if len(seg) == 1:                          # no listing all accounts
            raise HTTPException(403, "Not permitted")
        owner = await request.app.state.nessie.account_owner(seg[1])
        if owner and owner != customer:            # only your own account (by id)
            raise HTTPException(403, "Not permitted")


def _who(request: Request, user) -> dict:
    return {"actor": user["actor"] if "actor" in user.keys() else "external",
            "sid": user["sid"] if "sid" in user.keys() else None,
            "ip": request.client.host if request.client else None,
            "ua": request.headers.get("user-agent", "")[:300]}


async def _tell(request: Request, user, type_: str, data: dict) -> None:
    """Best-effort telemetry to the orchestrator, attributed to this session."""
    s = request.app.state.settings
    if not s.orchestrator_url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{s.orchestrator_url}/internal/event",
                         json={"username": user["username"], "type": type_, "source": "proxy",
                               "data": {**_who(request, user), **data}},
                         headers={"X-Internal-Secret": s.internal_secret})
    except httpx.HTTPError:
        pass


async def _log_request(request: Request, user, path: str, status: int) -> None:
    s = request.app.state.settings
    if not s.orchestrator_url:
        return
    seg = [p for p in path.split("/") if p]
    account_id = seg[1] if len(seg) > 1 and seg[0].lower() == "accounts" else None
    body = {"customer_id": user["nessie_customer_id"], "account_id": account_id,
            "method": request.method, "path": "/" + path, "status": status, **_who(request, user)}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{s.orchestrator_url}/internal/proxy-log", json=body,
                         headers={"X-Internal-Secret": s.internal_secret})
    except httpx.HTTPError:
        pass


def _money_op(method: str, path: str) -> tuple[str, str] | None:
    """(account_id, kind) when this is POST /accounts/{id}/<money sub-resource>."""
    seg = [p for p in path.split("/") if p]
    if method == "POST" and len(seg) == 3 and seg[0].lower() == "accounts" and seg[2].lower() in _MONEY:
        return seg[1], _MONEY[seg[2].lower()]
    return None


def _parse(raw: bytes) -> dict:
    try:
        d = json.loads(raw or b"{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def forward(path: str, request: Request, user=Depends(require_user)):
    await _enforce_scope(request, user, path)
    s = request.app.state.settings
    body = await request.body()
    money = _money_op(request.method, path)
    sent = _parse(body) if money else {}

    # Tripwire: the bank's per-transfer ceiling. Enforced here (Nessie has no such limit), declined
    # before anything reaches the ledger, and reported — a decline followed by a split is structuring.
    if money and money[1] in _LIMITED and s.transfer_limit_cents and \
            int(sent.get("amount_cents") or 0) > s.transfer_limit_cents:
        await _tell(request, user, "transfer.declined", {
            "kind": money[1], "payer_id": money[0], "payee_id": sent.get("payee_id"),
            "amount_cents": int(sent.get("amount_cents") or 0), "limit_cents": s.transfer_limit_cents,
            "reason": "transfer_limit_exceeded"})
        await _log_request(request, user, path, 422)
        return Response(json.dumps({
            "type": "transfer_limit_exceeded", "limit_cents": s.transfer_limit_cents,
            "detail": f"This exceeds the ${s.transfer_limit_cents / 100:,.2f} per-transfer limit. "
                      f"Split it into smaller transfers or visit a branch.",
        }), status_code=422, media_type="application/json")

    try:
        r = await request.app.state.nessie.forward(
            request.method, "/" + path, request.url.query.encode(), request.headers, body
        )
    except httpx.HTTPError:
        raise HTTPException(502, "Nessie unreachable")
    await _log_request(request, user, path, r.status_code)

    if money:
        got = _parse(r.content)
        got = got.get("objectCreated", got) if isinstance(got, dict) else {}
        await _tell(request, user, "money.attempt", {
            "kind": money[1], "payer_id": money[0], "payee_id": sent.get("payee_id") or got.get("payee_id"),
            "amount_cents": int(sent.get("amount_cents") or got.get("amount_cents") or 0),
            "tx_id": got.get("id") or got.get("_id"), "http_status": r.status_code,
            "status": "accepted" if r.status_code < 300 else "rejected",
            "reason": None if r.status_code < 300 else (got.get("type") or got.get("detail") or got.get("title")),
            "description": (sent.get("description") or "")[:120]})
    elif request.method in ("PATCH", "PUT") and path.strip("/").lower().startswith("customers/") and r.status_code < 300:
        # The customer record changed (address): the lockout/redirect half of an account takeover.
        await _tell(request, user, "contact.changed", {"fields": sorted(_parse(body)), "source": "customer"})
    return Response(r.content, status_code=r.status_code, headers=response_headers(r))
