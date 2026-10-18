from __future__ import annotations

import time

import httpx

_DROP_REQUEST = {"authorization", "host", "content-length", "connection", "accept-encoding", "cookie"}
_DROP_RESPONSE = {"content-encoding", "content-length", "transfer-encoding", "connection"}


class NessieError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail


class NessieClient:
    """The only module that holds the Nessie API key."""

    def __init__(self, base_url: str, api_key: str, transport: httpx.AsyncBaseTransport | None = None,
                 recorder=None):
        # recorder(method, path, status, ms, request_body, response_body) sees every upstream call.
        self._recorder = recorder
        hooks = {"request": [self._mark], "response": [self._record]} if recorder else {}
        self._http = httpx.AsyncClient(
            base_url=base_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=30, transport=transport,
            event_hooks=hooks,
        )
        self._owner_cache: dict[str, str] = {}  # account id -> owning customer id, per instance

    async def _mark(self, request: httpx.Request) -> None:
        request.extensions["t0"] = time.perf_counter()

    async def _record(self, response: httpx.Response) -> None:
        await response.aread()
        req = response.request
        ms = int((time.perf_counter() - req.extensions.get("t0", time.perf_counter())) * 1000)
        try:
            self._recorder(req.method, req.url.raw_path.decode(), response.status_code, ms,
                           (req.content or b"").decode("utf-8", "replace"), response.text)
        except Exception:
            pass

    async def aclose(self) -> None:
        await self._http.aclose()

    async def create_customer(self, body: dict) -> str:
        try:
            r = await self._http.post("/customers", json=body)
        except httpx.HTTPError as e:
            raise NessieError(502, f"Nessie unreachable: {type(e).__name__}")
        if r.status_code >= 400:
            raise NessieError(502 if r.status_code >= 500 or r.status_code in (401, 403) else 422,
                              f"Nessie rejected the customer ({r.status_code})")
        return r.json()["id"]

    async def delete_customer(self, customer_id: str) -> None:
        try:
            await self._http.delete(f"/customers/{customer_id}")
        except httpx.HTTPError:
            pass  # best effort

    async def account_owner(self, account_id: str) -> str | None:
        """Customer id that owns an account, cached. Used to keep a session scoped to its own data."""
        if account_id in self._owner_cache:
            return self._owner_cache[account_id]
        try:
            r = await self._http.get(f"/accounts/{account_id}/customer")
        except httpx.HTTPError:
            return None
        if r.status_code >= 400:
            return None
        d = r.json()
        owner = d.get("id") or d.get("_id")
        if owner:
            self._owner_cache[account_id] = owner
        return owner

    async def forward(self, method: str, path: str, query: bytes, headers, body: bytes) -> httpx.Response:
        fwd = {k: v for k, v in headers.items() if k.lower() not in _DROP_REQUEST}
        url = httpx.URL(path=path, query=query)
        # Passing per-request headers merges with the client default; the default Authorization (the real key) wins
        # because the caller's Authorization was dropped above.
        return await self._http.request(method, url, headers=fwd, content=body)


def response_headers(r: httpx.Response) -> dict:
    return {k: v for k, v in r.headers.items() if k.lower() not in _DROP_RESPONSE}
