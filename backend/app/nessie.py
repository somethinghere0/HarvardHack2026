"""Thin Nessie v2 client for the orchestrator's admin-level needs: registering the notify webhook
and (as a fallback) polling the resumable /events feed. Persona data is created through the proxy, not here, so this file is
small."""
from __future__ import annotations

import httpx


class NessieAdmin:
    def __init__(self, base_url: str, api_key: str):
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=30,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def create_webhook(self, url: str, events: list[str] | None = None) -> dict:
        """mode=notify hook. Empty events means every type. Returns the webhook incl. its signing
        `secret` (shown once by Nessie)."""
        body = {"mode": "notify", "url": url, "events": events or []}
        r = await self._http.post("/webhooks", json=body)
        r.raise_for_status()
        return r.json()

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
