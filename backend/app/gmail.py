from __future__ import annotations

import base64
import time

import httpx

API = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class GmailClient:
    """Minimal Gmail REST client. Mail is diverted from the inbox into a quarantine label by a Gmail filter at
    delivery time, so the user never sees an unverified message; releasing a message just moves it to the inbox."""

    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._creds = {"client_id": client_id, "client_secret": client_secret,
                       "refresh_token": refresh_token, "grant_type": "refresh_token"}
        self._http = httpx.AsyncClient(timeout=30, transport=transport)
        self._token = ""
        self._expires = 0.0
        self.labels: dict[str, str] = {}  # name -> id

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kw) -> dict:
        if time.monotonic() >= self._expires:
            r = await self._http.post(TOKEN_URL, data=self._creds)
            r.raise_for_status()
            body = r.json()
            self._token = body["access_token"]
            self._expires = time.monotonic() + body.get("expires_in", 3600) - 60
        r = await self._http.request(method, API + path, headers={"Authorization": f"Bearer {self._token}"}, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}

    async def ensure_labels(self, names: list[str]) -> None:
        existing = {l["name"]: l["id"] for l in (await self._request("GET", "/labels")).get("labels", [])}
        for name in names:
            if name not in existing:
                existing[name] = (await self._request("POST", "/labels", json={"name": name}))["id"]
            self.labels[name] = existing[name]

    async def ensure_quarantine_filter(self, quarantine: str) -> None:
        """Skip the inbox for all incoming mail and label it as quarantined (applied at delivery)."""
        qid = self.labels[quarantine]
        filters = (await self._request("GET", "/settings/filters")).get("filter", [])
        for f in filters:
            if qid in f.get("action", {}).get("addLabelIds", []):
                return
        await self._request("POST", "/settings/filters", json={
            "criteria": {"query": "-in:sent -in:drafts -from:me"},
            "action": {"addLabelIds": [qid], "removeLabelIds": ["INBOX"]},
        })

    async def list_pending(self, quarantine: str, held: str) -> list[str]:
        q = f'label:"{quarantine}" -label:"{held}"'
        data = await self._request("GET", "/messages", params={"q": q, "maxResults": 50})
        return [m["id"] for m in data.get("messages", [])]

    async def get_raw(self, message_id: str) -> bytes:
        data = await self._request("GET", f"/messages/{message_id}", params={"format": "raw"})
        return base64.urlsafe_b64decode(data["raw"] + "==")

    async def _modify(self, message_id: str, add: list[str], remove: list[str]) -> None:
        await self._request("POST", f"/messages/{message_id}/modify", json={"addLabelIds": add, "removeLabelIds": remove})

    async def release(self, message_id: str, quarantine: str) -> None:
        await self._modify(message_id, ["INBOX"], [self.labels[quarantine]])

    async def hold(self, message_id: str, held: str) -> None:
        await self._modify(message_id, [self.labels[held]], [])

    async def block(self, message_id: str, quarantine: str, scam: str) -> None:
        await self._modify(message_id, [self.labels[scam]], [self.labels[quarantine]])
