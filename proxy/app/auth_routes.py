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
    email: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)


class ProfileBody(BaseModel):
    email: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=32)


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


def who(request: Request) -> dict:
    """Who is at the keyboard, as far as the bank can tell: the decoy agent marks its own browser's
    requests with a header; anything else signing in to a decoy is a third party with phished
    credentials. Plus the client address and browser, for the engagement's intruder log."""
    s = request.app.state.settings
    actor = "agent" if request.headers.get(s.agent_header) else "external"
    return {"actor": actor, "ip": request.client.host if request.client else None,
            "ua": request.headers.get("user-agent", "")[:300]}


def _issue(request: Request, user_id: int) -> dict:
    s = request.app.state.settings
    token = new_token()
    w = who(request)
    sid = "s_" + secrets.token_hex(3)
    expires = db.create_session(s.db_path, user_id, hash_token(token), s.session_ttl_hours,
                                sid=sid, actor=w["actor"], ip=w["ip"], ua=w["ua"])
    return {"token": token, "expires_at": expires.isoformat(), "sid": sid}


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
        user_id = db.create_user(path, username, hash_password(body.password), customer_id,
                                 email=body.email, phone=body.phone)
    except sqlite3.IntegrityError:  # lost a race on the UNIQUE constraint
        await request.app.state.nessie.delete_customer(customer_id)
        raise HTTPException(409, "Username already taken")
    return {**_issue(request, user_id), "customer_id": customer_id}


@router.post("/login")
async def login(body: LoginBody, request: Request):
    s = request.app.state.settings
    user = db.get_user(s.db_path, body.username.lower())
    w = who(request)
    if not verify_password(user["password_hash"] if user else None, body.password):
        if user:  # a wrong password on a decoy account is still someone probing it
            await _orchestrator_post(request, "/internal/event", {
                "username": user["username"], "type": "login.failed", "source": "proxy", "data": w})
        raise HTTPException(401, "Invalid username or password", headers={"WWW-Authenticate": "Bearer"})
    # The password alone being right is the first canary: whoever typed it has the phished credential.
    await _orchestrator_post(request, "/internal/event", {
        "username": user["username"], "type": "login.password_ok", "source": "proxy", "data": w})
    if not s.otp_required:
        issued = _issue(request, user["id"])
        await _orchestrator_post(request, "/internal/event", {
            "username": user["username"], "type": "session.login", "source": "proxy",
            "data": {**w, "sid": issued["sid"]}})
        return issued
    # Second factor: issue a code, store only its hash, and have the orchestrator deliver it by email.
    code = f"{secrets.randbelow(1_000_000):06d}"
    challenge_id = secrets.token_urlsafe(18)
    db.create_challenge(s.db_path, challenge_id, user["id"], hash_token(code), s.otp_ttl_seconds)
    await _orchestrator_post(request, "/internal/send-otp",
                             {"username": user["username"], "challenge_id": challenge_id, "code": code,
                              **w})
    return {"otp_required": True, "challenge_id": challenge_id}


@router.post("/verify-otp")
async def verify_otp(body: OtpBody, request: Request):
    s = request.app.state.settings
    ch = db.get_challenge(s.db_path, body.challenge_id)
    if not ch or hash_token(body.code) != ch["code_hash"]:
        raise HTTPException(401, "Invalid or expired code")
    db.consume_challenge(s.db_path, body.challenge_id)
    user = db.get_user_by_id(s.db_path, ch["user_id"])
    issued = _issue(request, user["id"])
    await _orchestrator_post(request, "/internal/event", {
        "username": user["username"], "type": "session.login", "source": "proxy",
        "data": {**who(request), "sid": issued["sid"]},
    })
    return {**issued, "customer_id": user["nessie_customer_id"]}


@router.post("/logout", status_code=204, dependencies=[Depends(require_user)])
def logout(request: Request):
    db.delete_session(request.app.state.settings.db_path, hash_token(bearer_token(request)))
    return Response(status_code=204)


@router.get("/me")
def me(user=Depends(require_user)):
    return {"username": user["username"], "customer_id": user["nessie_customer_id"]}


@router.get("/profile")
def profile(user=Depends(require_user)):
    """Contact details the bank holds for the signed-in customer (where one-time codes go)."""
    return {"username": user["username"], "email": user["email"], "phone": user["phone"]}


@router.patch("/profile")
async def update_profile(body: ProfileBody, request: Request, user=Depends(require_user)):
    """Change the contact email/phone. Changing where the OTP goes is the classic account-takeover
    lockout move, so every change is reported with before/after values and who made it."""
    s = request.app.state.settings
    changes = {k: {"from": user[k], "to": v} for k, v in body.model_dump(exclude_none=True).items() if v != user[k]}
    if changes:
        db.update_user_contact(s.db_path, user["id"], **{k: v["to"] for k, v in changes.items()})
        await _orchestrator_post(request, "/internal/event", {
            "username": user["username"], "type": "contact.changed", "source": "proxy",
            "data": {"fields": sorted(changes), "changes": changes, "sid": user["sid"], "actor": user["actor"],
                     "ip": request.client.host if request.client else None,
                     "ua": request.headers.get("user-agent", "")[:300]},
        })
    fresh = db.get_user_by_id(s.db_path, user["id"])
    return {"username": fresh["username"], "email": fresh["email"], "phone": fresh["phone"], "changed": sorted(changes)}
