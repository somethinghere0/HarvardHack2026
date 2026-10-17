"""Email firewall. Polls the Gmail account and vets EVERY recent email: each is sent to the
orchestrator, which classifies it, records it on the dashboard, and (for credential-phishing) spins
up the honeypot. The watcher then acts on the verdict in Gmail — label scams as quarantined (and
optionally archive them out of the inbox), label safe mail as delivered.

App-password (SMTP/IMAP) mode only. Run alongside the stack:
    python backend/scripts/gmail_watcher.py

True pre-inbox holding: add a Gmail filter "Matches: *  ->  Skip the Inbox, Apply label: HoneybankPending"
and set GMAIL_SOURCE_LABEL=HoneybankPending. Then only mail this firewall clears (safe) is moved to
the inbox; everything else stays out of it."""
from __future__ import annotations

import os
import sys
import time

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.config import settings  # noqa: E402
from app.gmail_client import Gmail  # noqa: E402

POLL_SECONDS = int(os.environ.get("WATCH_POLL_SECONDS", "10"))
WATCH_LIMIT = int(os.environ.get("WATCH_LIMIT", "25"))


def _is_our_mail(s, m: dict) -> bool:
    """Skip the OTP/reply mail this system sends to itself (persona sub-addresses)."""
    local = s.gmail_address.split("@")[0].lower()
    sender = (m.get("sender") or "").lower()
    subj = (m.get("subject") or "").lower()
    return local and local in sender and ("bank of usa verification" in subj or subj.startswith("re:"))


def main() -> None:
    s = settings()
    if not s.gmail_app_password:
        raise SystemExit("The firewall watcher needs GMAIL_APP_PASSWORD (SMTP/IMAP mode).")
    gmail = Gmail(s)
    orch = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8001").rstrip("/")
    gmail.ensure_label(s.gmail_quarantine_label)
    gmail.ensure_label(s.gmail_safe_label)
    # Only vet mail that ARRIVES from now on: baseline at the current newest UID so existing inbox
    # history is left alone. Set WATCH_BACKFILL=1 to process what's already there too.
    backfill = os.environ.get("WATCH_BACKFILL", "0").strip().lower() in ("1", "true", "yes", "on")
    since_uid = 0 if backfill else gmail.max_uid(s.gmail_source_label)
    print(f"Email firewall: {s.gmail_address} [{s.gmail_source_label}] -> {orch} "
          f"(archive scams: {s.gmail_archive_scams}; watching for NEW mail"
          f"{' incl. backfill' if backfill else f' after uid {since_uid}'})")
    empty_polls = 0
    while True:
        try:
            batch = gmail.list_recent(s.gmail_source_label, limit=WATCH_LIMIT, since_uid=since_uid)
            if batch:
                since_uid = max(since_uid, max(int(m["uid"]) for m in batch))
                empty_polls = 0
                print(f"[watcher] {len(batch)} new message(s) in {s.gmail_source_label}")
            else:
                empty_polls += 1
                if empty_polls == 6:  # ~1 min of nothing
                    print(f"[watcher] no new mail yet in {s.gmail_source_label}. If a message you sent "
                          "isn't picked up, check IMAP is enabled and GMAIL_ADDRESS/GMAIL_APP_PASSWORD.")
            for m in batch:
                if _is_our_mail(s, m):
                    continue
                try:
                    r = httpx.post(f"{orch}/ingest-email",
                                   json={k: m.get(k) for k in ("gmail_id", "sender", "subject", "body")},
                                   timeout=90).json()
                except httpx.HTTPError as e:
                    print(f"[watcher] ingest failed: {e}")
                    continue
                if r.get("already_processed"):
                    continue
                if r.get("verdict") == "scam":
                    gmail.apply_label(m["uid"], s.gmail_quarantine_label, m["folder"])
                    if s.gmail_archive_scams:
                        gmail.archive(m["uid"], m["folder"])
                    print(f"[SCAM {r.get('classification',{}).get('vector','')}] "
                          f"{m.get('subject','')[:50]} -> quarantined")
                else:
                    if s.gmail_safe_label:
                        gmail.apply_label(m["uid"], s.gmail_safe_label, m["folder"])
                    print(f"[safe] {m.get('subject','')[:50]} -> delivered")
        except Exception as e:  # keep the loop alive
            print(f"[watcher] {type(e).__name__}: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
