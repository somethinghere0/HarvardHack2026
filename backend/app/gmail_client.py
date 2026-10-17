"""Gmail access for the orchestrator: sending OTP/reply mail and (for the watcher) reading inbound
mail. Three modes, picked automatically:

  - FAKE  (GMAIL_FAKE=1): nothing touches Google; sends are recorded, inbound arrives via /api/sim.
  - app password (GMAIL_APP_PASSWORD set): SMTP + IMAP over the stdlib. Simplest real setup — turn on
    2-Step Verification, generate a 16-char App Password, paste it in. No GCP project, no OAuth.
  - OAuth (neither of the above): Gmail API with user credentials (see scripts/gmail_authorize.py).

All three expose the same send / list_unread / mark_read methods.
"""
from __future__ import annotations

import base64
import email
import imaplib
import smtplib
import ssl
from email.mime.text import MIMEText

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]
_IMAP_HOST = "imap.gmail.com"
_SMTP_HOST = "smtp.gmail.com"


class Gmail:
    def __init__(self, s):
        self.s = s
        if s.gmail_fake:
            self.mode = "fake"
        elif s.gmail_app_password:
            self.mode = "app_password"
        else:
            self.mode = "oauth"
        self._svc = None

    # ---- send ----------------------------------------------------------------

    def send(self, to: str, subject: str, body: str) -> dict:
        if self.mode == "fake":
            return {"fake": True, "to": to, "subject": subject}
        msg = MIMEText(body)
        msg["To"], msg["From"], msg["Subject"] = to, self.s.gmail_address, subject
        if self.mode == "app_password":
            with smtplib.SMTP_SSL(_SMTP_HOST, 465, context=ssl.create_default_context()) as smtp:
                smtp.login(self.s.gmail_address, self.s.gmail_app_password)
                smtp.send_message(msg)
            return {"sent": True, "to": to}
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        return self._service().users().messages().send(userId="me", body={"raw": raw}).execute()

    # ---- read (watcher) ------------------------------------------------------

    def list_unread(self) -> list[dict]:
        """[{id, thread_id, sender, recipient, subject, body}] for unread inbox mail. Not FAKE mode."""
        if self.mode == "fake":
            return []
        if self.mode == "app_password":
            return self._imap_unread()
        svc = self._service()
        res = svc.users().messages().list(userId="me", q="is:unread -in:sent", labelIds=["INBOX"]).execute()
        out = []
        for m in res.get("messages", []):
            full = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
            out.append(_parse_api_message(full))
        return out

    def mark_read(self, message_id: str) -> None:
        if self.mode == "fake":
            return
        if self.mode == "app_password":
            with self._imap() as M:
                M.select("INBOX")
                M.uid("store", message_id, "+FLAGS", "(\\Seen)")
            return
        self._service().users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}).execute()

    # ---- IMAP (app-password mode) -------------------------------------------

    def _imap(self) -> imaplib.IMAP4_SSL:
        M = imaplib.IMAP4_SSL(_IMAP_HOST)
        M.login(self.s.gmail_address, self.s.gmail_app_password)
        return M

    def _imap_unread(self) -> list[dict]:
        out = []
        with self._imap() as M:
            M.select("INBOX")
            typ, data = M.uid("search", None, "UNSEEN")
            if typ != "OK":
                return out
            for uid in data[0].split():
                # BODY.PEEK leaves the message unread until we explicitly mark_read it.
                t, fetched = M.uid("fetch", uid, "(BODY.PEEK[])")
                if t != "OK" or not fetched or not fetched[0]:
                    continue
                msg = email.message_from_bytes(fetched[0][1])
                out.append({
                    "id": uid.decode(), "thread_id": msg.get("Message-ID", ""),
                    "sender": msg.get("From", ""), "recipient": msg.get("To", ""),
                    "subject": msg.get("Subject", ""), "body": _imap_body(msg),
                })
        return out

    # ---- OAuth (advanced mode) ----------------------------------------------

    def _service(self):
        if self._svc is not None:
            return self._svc
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(self.s.gmail_token_file, GMAIL_SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        self._svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._svc


def _imap_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", "replace").strip()
        return ""
    payload = msg.get_payload(decode=True)
    return payload.decode(msg.get_content_charset() or "utf-8", "replace").strip() if payload else ""


def _parse_api_message(full: dict) -> dict:
    headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
    return {
        "id": full["id"], "thread_id": full.get("threadId"),
        "sender": headers.get("from", ""), "recipient": headers.get("to", ""),
        "subject": headers.get("subject", ""), "body": _api_body(full.get("payload", {})),
    }


def _api_body(payload: dict) -> str:
    def walk(part) -> str:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "replace")
        for p in part.get("parts", []) or []:
            t = walk(p)
            if t:
                return t
        return ""
    return walk(payload).strip()
