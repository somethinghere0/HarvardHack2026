"""Gmail access for the orchestrator: sending OTP/reply mail and (for the watcher) reading inbound
mail. In FAKE mode nothing touches Google — sends are recorded and inbound mail arrives through the
/api/sim endpoints instead, so the demo runs with no OAuth setup.

Real mode uses OAuth user credentials (not a service account). Generate the token file once with the
companion script scripts/gmail_authorize.py. Scopes needed:
  https://www.googleapis.com/auth/gmail.send      (send OTP + replies)
  https://www.googleapis.com/auth/gmail.modify    (read inbound, mark read)
"""
from __future__ import annotations

import base64
from email.mime.text import MIMEText

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


class Gmail:
    def __init__(self, s):
        self.s = s
        self._svc = None

    def _service(self):
        if self._svc is not None:
            return self._svc
        # Lazy imports so FAKE mode needs none of the Google libraries installed.
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(self.s.gmail_token_file, GMAIL_SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        self._svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._svc

    def send(self, to: str, subject: str, body: str) -> dict:
        if self.s.gmail_fake:
            return {"fake": True, "to": to, "subject": subject}
        msg = MIMEText(body)
        msg["to"] = to
        msg["from"] = self.s.gmail_address
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return self._service().users().messages().send(userId="me", body={"raw": raw}).execute()

    def list_unread(self) -> list[dict]:
        """Returns [{id, thread_id, sender, recipient, subject, body}] for unread inbox mail. Real mode only."""
        if self.s.gmail_fake:
            return []
        svc = self._service()
        res = svc.users().messages().list(userId="me", q="is:unread -in:sent", labelIds=["INBOX"]).execute()
        out = []
        for m in res.get("messages", []):
            full = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
            out.append(_parse_message(full))
        return out

    def mark_read(self, message_id: str) -> None:
        if self.s.gmail_fake:
            return
        self._service().users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}).execute()


def _parse_message(full: dict) -> dict:
    headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
    return {
        "id": full["id"],
        "thread_id": full.get("threadId"),
        "sender": headers.get("from", ""),
        "recipient": headers.get("to", ""),
        "subject": headers.get("subject", ""),
        "body": _extract_body(full.get("payload", {})),
    }


def _extract_body(payload: dict) -> str:
    def walk(part) -> str:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "replace")
        for p in part.get("parts", []) or []:
            t = walk(p)
            if t:
                return t
        return ""
    return walk(payload).strip()
