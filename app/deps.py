from __future__ import annotations

from fastapi import HTTPException, Request

from . import db
from .security import hash_token


def bearer_token(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(401, "Missing session token", headers={"WWW-Authenticate": "Bearer"})
    return token.strip()


def require_user(request: Request):
    user = db.get_session_user(request.app.state.settings.db_path, hash_token(bearer_token(request)))
    if user is None:
        raise HTTPException(401, "Invalid or expired session", headers={"WWW-Authenticate": "Bearer"})
    return user
