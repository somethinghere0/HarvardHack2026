"""Calls the auth proxy the same way a browser would, so personas are created through the real
signup + Nessie path (not a side door). Returns the session token used to seed accounts/history."""
from __future__ import annotations

import httpx


class ProxyClient:
    def __init__(self, base_url: str):
        self._base = base_url.rstrip("/")

    async def signup(self, body: dict) -> dict:
        """-> {token, expires_at, customer_id}."""
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self._base}/auth/signup", json=body)
            r.raise_for_status()
            return r.json()

    async def login(self, username: str, password: str) -> dict:
        """-> {otp_required, challenge_id} (normal path) or {token, ...} if OTP disabled."""
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self._base}/auth/login", json={"username": username, "password": password})
            r.raise_for_status()
            return r.json()

    async def verify_otp(self, challenge_id: str, code: str) -> dict:
        """-> {token, expires_at, customer_id}."""
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self._base}/auth/verify-otp",
                             json={"challenge_id": challenge_id, "code": code})
            r.raise_for_status()
            return r.json()

    async def transfer(self, token: str, from_id: str, payee_id: str, amount_cents: int,
                       description: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self._base}/accounts/{from_id}/transfers",
                             json={"payee_id": payee_id, "amount_cents": amount_cents,
                                   "description": description},
                             headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            return _unwrap(r.json())

    async def accounts(self, token: str, customer_id: str) -> list:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self._base}/customers/{customer_id}/accounts",
                            headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            d = r.json()
            return d if isinstance(d, list) else (d.get("items") or d.get("data") or [])

    async def open_account(self, token: str, customer_id: str, account: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self._base}/customers/{customer_id}/accounts", json=account,
                             headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            return _unwrap(r.json())

    async def deposit(self, token: str, account_id: str, amount_cents: int, description: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{self._base}/accounts/{account_id}/deposits",
                             json={"amount_cents": amount_cents, "description": description},
                             headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            return _unwrap(r.json())


def _unwrap(d):
    # Nessie v1 wrapped created objects in {objectCreated}; v2 returns the object. Handle both.
    return d.get("objectCreated", d) if isinstance(d, dict) else d
