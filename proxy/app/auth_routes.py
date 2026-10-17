from __future__ import annotations

import secrets
import sqlite3

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import db
from .deps import bearer_token, require_user
from .nessie import NessieError
from .rate_limit import limit_auth
from .security import hash_password, hash_token, new_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(limit_auth)])


class Address(BaseModel):
    street_number: str = Field(max_length=12)
    street_name: str = Field(max_length=80)
    city: str = Field(max_length=80)
    state: str = Field(min_length=2, max_length=2)
    zip: str = Field(pattern=r"^[0-9]{5}$")


class SignupBody(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    address: Address


class LoginBody(BaseModel):
    username: str = Field(max_length=32)
    password: str = Field(max_length=128)


class OtpBody(BaseModel):
    challenge_id: str = Field(max_length=64)
    code: str = Field(min_length=4, max_length=12)


async def _orchestrator_post(request: Request, path: str, body: dict) -> None:
    """Best-effort internal call to the orchestrator (OTP email, login telemetry)."""
    s = request.app.state.settings
    if not s.orchestrator_url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            await c.post(f"{s.orchestrator_url}{path}", json=body,
                         headers={"X-Internal-Secret": s.internal_secret})
    except httpx.HTTPError:
        pass


def _issue(request: Request, user_id: int) -> dict:
    s = request.app.state.settings
    token = new_token()
    expires = db.create_session(s.db_path, user_id, hash_token(token), s.session_ttl_hours)
    return {"token": token, "expires_at": expires.isoformat()}


@router.post("/signup", status_code=201)
async def signup(body: SignupBody, request: Request):
    path = request.app.state.settings.db_path
    username = body.username.lower()
    if db.get_user(path, username):
        raise HTTPException(409, "Username already taken")
    try:
        customer_id = await request.app.state.nessie.create_customer(
            body.model_dump(include={"first_name", "last_name", "address"})
        )
    except NessieError as e:
        raise HTTPException(e.status, e.detail)
    try:
        user_id = db.create_user(path, username, hash_password(body.password), customer_id)
    except sqlite3.IntegrityError:  # lost a race on the UNIQUE constraint
        await request.app.state.nessie.delete_customer(customer_id)
        raise HTTPException(409, "Username already taken")
    return {**_issue(request, user_id), "customer_id": customer_id}


@router.post("/login")
async def login(body: LoginBody, request: Request):
    s = request.app.state.settings
    user = db.get_user(s.db_path, body.username.lower())
    if not verify_password(user["password_hash"] if user else None, body.password):
        raise HTTPException(401, "Invalid username or password", headers={"WWW-Authenticate": "Bearer"})
    if not s.otp_required:
        return _issue(request, user["id"])
    # Second factor: issue a code, store only its hash, and have the orchestrator deliver it by email.
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge_id = secrets.token_urlsafe(18)
    db.create_challenge(s.db_path, challenge_id, user["id"], hash_token(code), s.otp_ttl_seconds)
    await _orchestrator_post(request, "/internal/send-otp",
                             {"username": user["username"], "challenge_id": challenge_id, "code": code})
    return {"otp_required": True, "challenge_id": challenge_id}


@router.post("/verify-otp")
async def verify_otp(body: OtpBody, request: Request):
    s = request.app.state.settings
    ch = db.get_challenge(s.db_path, body.challenge_id)
    if not ch or hash_token(body.code) != ch["code_hash"]:
        raise HTTPException(401, "Invalid or expired code")
    db.consume_challenge(s.db_path, body.challenge_id)
    user = db.get_user_by_id(s.db_path, ch["user_id"])
    ip = request.client.host if request.client else None
    await _orchestrator_post(request, "/internal/event", {
        "username": user["username"], "type": "session.login", "source": "proxy",
        "data": {"ip": ip, "ua": request.headers.get("user-agent", "")},
    })
    return {**_issue(request, user["id"]), "customer_id": user["nessie_customer_id"]}


@router.post("/logout", status_code=204, dependencies=[Depends(require_user)])
def logout(request: Request):
    db.delete_session(request.app.state.settings.db_path, hash_token(bearer_token(request)))
    return Response(status_code=204)


@router.get("/me")
def me(user=Depends(require_user)):
    return {"username": user["username"], "customer_id": user["nessie_customer_id"]}
