from __future__ import annotations

import sqlite3

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
def login(body: LoginBody, request: Request):
    user = db.get_user(request.app.state.settings.db_path, body.username.lower())
    if not verify_password(user["password_hash"] if user else None, body.password):
        raise HTTPException(401, "Invalid username or password", headers={"WWW-Authenticate": "Bearer"})
    return _issue(request, user["id"])


@router.post("/logout", status_code=204, dependencies=[Depends(require_user)])
def logout(request: Request):
    db.delete_session(request.app.state.settings.db_path, hash_token(bearer_token(request)))
    return Response(status_code=204)


@router.get("/me")
def me(user=Depends(require_user)):
    return {"username": user["username"], "customer_id": user["nessie_customer_id"]}
