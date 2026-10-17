from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .deps import require_user
from .nessie import response_headers

router = APIRouter(dependencies=[Depends(require_user)])

# Paths whose first segment is a shared/global collection a session may always read.
_GLOBAL = {"events", "atms", "branches", "merchants", "enums", "health"}


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


async def _log_request(request: Request, user, path: str, status: int) -> None:
    s = request.app.state.settings
    if not s.orchestrator_url:
        return
    seg = [p for p in path.split("/") if p]
    account_id = seg[1] if len(seg) > 1 and seg[0].lower() == "accounts" else None
    body = {"customer_id": user["nessie_customer_id"], "account_id": account_id,
            "method": request.method, "path": "/" + path, "status": status,
            "ip": request.client.host if request.client else None,
            "ua": request.headers.get("user-agent", "")}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{s.orchestrator_url}/internal/proxy-log", json=body,
                         headers={"X-Internal-Secret": s.internal_secret})
    except httpx.HTTPError:
        pass


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def forward(path: str, request: Request, user=Depends(require_user)):
    await _enforce_scope(request, user, path)
    try:
        r = await request.app.state.nessie.forward(
            request.method, "/" + path, request.url.query.encode(), request.headers, await request.body()
        )
    except httpx.HTTPError:
        raise HTTPException(502, "Nessie unreachable")
    await _log_request(request, user, path, r.status_code)
    return Response(r.content, status_code=r.status_code, headers=response_headers(r))
