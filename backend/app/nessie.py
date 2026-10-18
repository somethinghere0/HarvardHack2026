"""Thin Nessie v2 client for the orchestrator's admin-level needs: registering the notify webhook
and (as a fallback) polling the resumable /events feed. Persona data is created through the proxy, not here, so this file is
small."""
from __future__ import annotations

import time

import httpx


class NessieHTTPError(Exception):
    def __init__(self, status: int, detail):
        super().__init__(f"Nessie {status}: {detail}")
        self.status, self.detail = status, detail


class NessieAdmin:
    """`recorder(method, path, status, ms, request_body, response_body)` is called after every
    request, so the dashboard can show each Nessie call this client makes."""

    def __init__(self, base_url: str, api_key: str, recorder=None):
        hooks = {"request": [self._mark], "response": [self._record]} if recorder else {}
        self._recorder = recorder
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=30, event_hooks=hooks,
        )

    async def _mark(self, request: httpx.Request) -> None:
        request.extensions["t0"] = time.perf_counter()

    async def _record(self, response: httpx.Response) -> None:
        await response.aread()
        req = response.request
        ms = int((time.perf_counter() - req.extensions.get("t0", time.perf_counter())) * 1000)
        path = req.url.raw_path.decode()
        try:
            self._recorder(req.method, path, response.status_code, ms,
                           (req.content or b"").decode("utf-8", "replace"), response.text)
        except Exception:
            pass  # logging must never break a bank call

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(self, method: str, path: str, json: dict | None = None, params: dict | None = None):
        """Raw call; returns the parsed JSON (or {}) and raises for 4xx/5xx with Nessie's problem body."""
        r = await self._http.request(method, path, json=json, params=params)
        if r.status_code >= 400:
            try:
                detail = r.json()
            except ValueError:
                detail = {"detail": r.text[:200]}
            raise NessieHTTPError(r.status_code, detail)
        try:
            return r.json() if r.content else {}
        except ValueError:
            return {}

    async def list_webhooks(self) -> list[dict]:
        d = await self.request("GET", "/webhooks")
        return d if isinstance(d, list) else (d.get("items") or d.get("data") or [])

    async def create_decision_hook(self, url: str, kinds: list[str], max_wait: int = 20,
                                   on_error: str = "approve") -> dict:
        """A decision hook: Nessie calls `url` while a matching transaction is pending and settles it
        the way we answer. One per kind per key."""
        return await self.request("POST", "/webhooks", json={"mode": "decision", "url": url, "kinds": kinds,
                                                             "max_wait_seconds": max_wait, "on_error": on_error})

    async def get_transaction(self, tx_id: str) -> dict:
        return await self.request("GET", f"/transactions/{tx_id}")

    async def decide_transaction(self, tx_id: str, decision: str, reason: str = "") -> dict:
        body = {"decision": decision}
        if reason:
            body["reason"] = reason[:200]
        return await self.request("POST", f"/transactions/{tx_id}/decision", json=body)

    async def cancel_transaction(self, tx_id: str) -> dict:
        return await self.request("POST", f"/transactions/{tx_id}/cancel")

    async def create_customer(self, body: dict) -> dict:
        return await self.request("POST", "/customers", json=body)

    async def create_account(self, customer_id: str, body: dict) -> dict:
        return await self.request("POST", f"/customers/{customer_id}/accounts", json=body)

    async def transfer(self, payer_id: str, payee_id: str, amount_cents: int, description: str = "") -> dict:
        return await self.request("POST", f"/accounts/{payer_id}/transfers",
                                  json={"medium": "balance", "payee_id": payee_id, "amount_cents": amount_cents,
                                        "description": description[:120]})

    async def withdraw(self, account_id: str, amount_cents: int, description: str = "") -> dict:
        return await self.request("POST", f"/accounts/{account_id}/withdrawals",
                                  json={"medium": "balance", "amount_cents": amount_cents, "description": description[:120]})

    async def deposit(self, account_id: str, amount_cents: int, description: str = "") -> dict:
        return await self.request("POST", f"/accounts/{account_id}/deposits",
                                  json={"medium": "balance", "amount_cents": amount_cents, "description": description[:120]})

    async def create_webhook(self, url: str, events: list[str] | None = None) -> dict:
        """mode=notify hook. Empty events means every type. Returns the webhook incl. its signing
        `secret` (shown once by Nessie)."""
        body = {"mode": "notify", "url": url, "events": events or []}
        r = await self._http.post("/webhooks", json=body)
        r.raise_for_status()
        return r.json()

    async def get_account(self, account_id: str) -> dict:
        r = await self._http.get(f"/accounts/{account_id}")
        r.raise_for_status()
        return r.json()

    async def list_transactions(self, account_id: str, limit: int = 100) -> list[dict]:
        r = await self._http.get(f"/accounts/{account_id}/transactions", params={"limit": limit})
        r.raise_for_status()
        d = r.json()
        return d.get("items", d) if isinstance(d, dict) else d

    async def get_customer(self, customer_id: str) -> dict:
        r = await self._http.get(f"/customers/{customer_id}")
        r.raise_for_status()
        return r.json()

    async def settle_transaction(self, tx_id: str) -> None:
        """Fast-forward a pending transaction (Nessie holds new ones pending before they post)."""
        r = await self._http.post(f"/transactions/{tx_id}/settle")
        r.raise_for_status()

    async def delete_webhook(self, webhook_id: str) -> None:
        try:
            await self._http.delete(f"/webhooks/{webhook_id}")
        except httpx.HTTPError:
            pass  # best effort on shutdown

    async def ping_webhook(self, webhook_id: str) -> None:
        await self._http.post(f"/webhooks/{webhook_id}/ping")

    async def get_events(self, after: int | str | None = None, limit: int = 200,
                         types: list[str] | None = None) -> tuple[list[dict], int | str | None]:
        """Nessie v2 returns {"items":[...], "next_cursor":N}. Returns (items, next_cursor)."""
        params: dict = {"limit": min(limit, 500)}
        if after is not None:
            params["after"] = after
        if types:
            params["types"] = ",".join(types)
        r = await self._http.get("/events", params=params)
        r.raise_for_status()
        d = r.json()
        if isinstance(d, list):
            return d, None
        items = d.get("items") or d.get("data") or d.get("events") or []
        return items, d.get("next_cursor")


def logged(s, scope: str) -> "NessieAdmin":
    """A client whose every call lands in the nessie_calls log under `scope`."""
    from . import db
    return NessieAdmin(s.nessie_base_url, s.nessie_api_key,
                       recorder=lambda m, p, st, ms, rq, rs: db.add_nessie_call(s.db_path, scope, m, p, st, ms, rq, rs))
