"""Polls the real Gmail inbox and feeds inbound mail to the orchestrator. Real mode only — in FAKE
mode use the /api/sim endpoints instead. Run alongside the orchestrator:

    GMAIL_FAKE=0 python backend/scripts/gmail_watcher.py

Each unread message is routed by recipient: mail to inbox+persona_<id>@... that comes from our own
Honeybank OTP sender is recorded as an OTP for that persona; anything else is handed to
/sim/inbound-email for classification (which opens an engagement if it looks like a scam)."""
from __future__ import annotations

import os
import sys
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.config import settings  # noqa: E402
from app.gmail_client import Gmail  # noqa: E402

POLL_SECONDS = int(os.environ.get("WATCH_POLL_SECONDS", "10"))


def main() -> None:
    s = settings()
    if s.gmail_fake:
        raise SystemExit("GMAIL_FAKE is on; the watcher is only for real Gmail. Use /api/sim/* for demos.")
    gmail = Gmail(s)
    orch = os.environ.get("ORCHESTRATOR_PUBLIC_URL", "http://127.0.0.1:8001")
    print(f"Watching {s.gmail_address} every {POLL_SECONDS}s -> {orch}")
    while True:
        try:
            for msg in gmail.list_unread():
                _route(orch, s, msg)
                gmail.mark_read(msg["id"])
        except Exception as e:  # keep the loop alive
            print(f"[watcher] {type(e).__name__}: {e}")
        time.sleep(POLL_SECONDS)


def _route(orch: str, s, msg: dict) -> None:
    sender = msg.get("sender", "")
    # Our own OTP mail: ignore here (the orchestrator already stored the code when it sent it).
    if s.gmail_address.split("@")[0] in sender and "honeybank" in msg.get("subject", "").lower():
        print(f"[watcher] OTP mail seen for {msg.get('recipient')}")
        return
    try:
        httpx.post(f"{orch}/sim/inbound-email", json={
            "sender": sender, "subject": msg.get("subject", ""), "body": msg.get("body", ""),
        }, timeout=30)
        print(f"[watcher] forwarded: {msg.get('subject','')[:60]}")
    except httpx.HTTPError as e:
        print(f"[watcher] forward failed: {e}")


if __name__ == "__main__":
    main()
