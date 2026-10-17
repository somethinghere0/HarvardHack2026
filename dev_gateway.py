"""Dev-only stand-in for frontend/nginx.conf: serves the static frontend and reverse-proxies
/bank-api/* -> auth proxy and /api/* -> orchestrator, stripping the prefix exactly like nginx.
Used by dev.py; not part of the Docker stack (nginx does this in containers)."""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

FRONTEND = os.environ.get("FRONTEND_DIR", "frontend")
PROXY_URL = os.environ.get("DEV_PROXY_URL", "http://127.0.0.1:8000")
ORCH_URL = os.environ.get("DEV_ORCH_URL", "http://127.0.0.1:8001")
PORTAL_URL = os.environ.get("DEV_PORTAL_URL", "http://127.0.0.1:8080")
_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]

app = FastAPI()


async def _forward(base: str, path: str, request: Request) -> Response:
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.request(
            request.method, f"{base}/{path}", params=request.query_params,
            headers={k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")},
            content=await request.body(),
        )
    drop = ("content-length", "content-encoding", "transfer-encoding", "connection")
    return Response(r.content, status_code=r.status_code,
                    headers={k: v for k, v in r.headers.items() if k.lower() not in drop})


@app.api_route("/bank-api/{path:path}", methods=_METHODS)
async def bank_api(path: str, request: Request):
    return await _forward(PROXY_URL, path, request)


@app.api_route("/api/{path:path}", methods=_METHODS)
async def api(path: str, request: Request):
    return await _forward(ORCH_URL, path, request)


# The decoy portal is reachable at /portal and /portal/* (its forms post to /portal/login, /portal/otp).
@app.api_route("/portal", methods=_METHODS)
async def portal_root(request: Request):
    return await _forward(PORTAL_URL, "portal", request)


@app.api_route("/portal/{path:path}", methods=_METHODS)
async def portal(path: str, request: Request):
    return await _forward(PORTAL_URL, f"portal/{path}", request)


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="static")
