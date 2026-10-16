from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .deps import require_user
from .nessie import response_headers

router = APIRouter(dependencies=[Depends(require_user)])


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def forward(path: str, request: Request):
    try:
        r = await request.app.state.nessie.forward(
            request.method, "/" + path, request.url.query.encode(), request.headers, await request.body()
        )
    except httpx.HTTPError:
        raise HTTPException(502, "Nessie unreachable")
    return Response(r.content, status_code=r.status_code, headers=response_headers(r))
