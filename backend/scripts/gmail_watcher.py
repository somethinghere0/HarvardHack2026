"""Email firewall. Polls the Gmail account and sends EVERY new email to the orchestrator, which
detonates it in a sandbox: a decoy victim does what the email asks, and the verdict is what that
cost the decoy. Detonation takes minutes, so the watcher keeps each email pending and acts once its
verdict lands — label scams as quarantined (and optionally archive them out of the inbox), label
safe mail as delivered. An inconclusive run is left untouched for a human to look at.

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
# After labelling, keep checking a message's verdict this long: a transfer the ledger records late
# flips a "safe" to "scam" after the fact, and the label has to follow it.
RELABEL_SECONDS = int(os.environ.get("WATCH_RELABEL_SECONDS", "900"))


def _is_our_mail(s, m: dict) -> bool:
    """Mail this system sent to itself: OTP codes (and any reply) addressed to a persona sub-address
    (inbox+persona_<id>@...). The sub-address is minted per sandbox, so a message FROM our own address
    TO one of them is the bank talking to its decoy, never something a human needs to vet or read.
    Mail from anyone else to a persona address is a scammer following up — that still gets detonated."""
    addr = s.gmail_address.lower()
    local = addr.split("@")[0]
    sender = (m.get("sender") or "").lower()
    recipient = (m.get("recipient") or "").lower()
    subj = (m.get("subject") or "").lower()
    if not local or (addr not in sender and f"{local}@" not in sender):
        return False
    return "+persona_" in recipient or "bank of usa verification" in subj or subj.startswith("re:")


def _hide_internal(gmail, s, m: dict) -> None:
    """Keep back-channel mail out of the inbox: file it under the internal label (still in All Mail)
    and archive it from the watched folder. Never trashed."""
    subj = m.get("subject", "")[:50]
    if not s.gmail_hide_internal_mail:
        print(f"[internal] {subj} -> left in place (GMAIL_HIDE_INTERNAL_MAIL=0)")
        return
    try:
        gmail.apply_label(m["uid"], s.gmail_internal_label, m["folder"])
        gmail.archive(m["uid"], m["folder"])
        print(f"[internal] {subj} -> filed under {s.gmail_internal_label}, hidden from inbox")
    except Exception as e:
        print(f"[watcher] couldn't hide internal mail '{subj}': {type(e).__name__}: {e}")


def _label_for(s, verdict: str) -> str | None:
    return {"scam": s.gmail_quarantine_label, "safe": s.gmail_safe_label or None}.get(verdict)


def _act(gmail, s, m: dict, v: dict, previous: str | None = None) -> None:
    """Label a message for its verdict. With `previous` (a verdict already acted on), this is a flip:
    the old label comes off first, so a "safe" the ledger later proved wrong doesn't stay marked safe."""
    subj = m.get("subject", "")[:50]
    old = _label_for(s, previous) if previous else None
    if old and old != _label_for(s, v["verdict"]):
        try:
            removed = gmail.remove_label(m.get("gmail_id", ""), old)
        except Exception as e:
            removed = False
            print(f"[watcher] couldn't remove {old} from '{subj}': {type(e).__name__}: {e}")
        print(f"[flip] {subj}: {previous} -> {v['verdict']} ({old} {'removed' if removed else 'NOT removed'})")
    if v["verdict"] == "scam":
        gmail.apply_label(m["uid"], s.gmail_quarantine_label, m["folder"])
        if s.gmail_archive_scams:
            gmail.archive(m["uid"], m["folder"])
        print(f"[SCAM {v.get('vector') or ''}] {subj} -> quarantined: {(v.get('reason') or '')[:120]}")
    elif v["verdict"] == "safe":
        if s.gmail_safe_label:
            gmail.apply_label(m["uid"], s.gmail_safe_label, m["folder"])
        print(f"[safe] {subj} -> delivered")
    else:
        print(f"[review] {subj} -> sandbox run inconclusive, left as-is")


def main() -> None:
    s = settings()
    if not s.gmail_app_password:
        raise SystemExit("The firewall watcher needs GMAIL_APP_PASSWORD (SMTP/IMAP mode).")
    gmail = Gmail(s)
    orch = os.environ.get("ORCHESTRATOR_URL", "http://127.0.0.1:8001").rstrip("/")
    gmail.ensure_label(s.gmail_quarantine_label)
    gmail.ensure_label(s.gmail_safe_label)
    gmail.ensure_label(s.gmail_internal_label)
    # Only vet mail that ARRIVES from now on: baseline at the current newest UID so existing inbox
    # history is left alone. Set WATCH_BACKFILL=1 to process what's already there too.
    backfill = os.environ.get("WATCH_BACKFILL", "0").strip().lower() in ("1", "true", "yes", "on")
    since_uid = 0 if backfill else gmail.max_uid(s.gmail_source_label)
    print(f"Email firewall: {s.gmail_address} [{s.gmail_source_label}] -> {orch} "
          f"(archive scams: {s.gmail_archive_scams}; watching for NEW mail"
          f"{' incl. backfill' if backfill else f' after uid {since_uid}'})")
    empty_polls = 0
    pending: dict[str, dict] = {}  # gmail_id -> message, still detonating
    judged: dict[str, tuple[dict, str, float]] = {}  # gmail_id -> (message, verdict acted on, when)
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
                    _hide_internal(gmail, s, m)
                    continue
                try:
                    r = httpx.post(f"{orch}/ingest-email",
                                   json={k: m.get(k) for k in ("gmail_id", "sender", "subject", "body")},
                                   timeout=30).json()
                except httpx.HTTPError as e:
                    print(f"[watcher] ingest failed: {e}")
                    continue
                if r.get("already_processed") or not m.get("gmail_id"):
                    continue
                pending[m["gmail_id"]] = m
                print(f"[held] {m.get('subject','')[:50]} -> detonating in sandbox")
            now = time.time()
            for gid in [g for g, (_, _, at) in judged.items() if now - at > RELABEL_SECONDS]:
                judged.pop(gid)
            if pending or judged:
                done = httpx.post(f"{orch}/verdicts", json={"gmail_ids": list(pending) + list(judged)},
                                  timeout=15).json()
                for gid, v in (done.get("verdicts") or {}).items():
                    if v.get("verdict") == "pending":
                        continue
                    if gid in pending:
                        m = pending.pop(gid)
                        _act(gmail, s, m, v)
                        judged[gid] = (m, v["verdict"], now)
                    elif gid in judged and v["verdict"] != judged[gid][1]:
                        m, prev, _ = judged[gid]
                        _act(gmail, s, m, v, previous=prev)
                        judged[gid] = (m, v["verdict"], now)
        except Exception as e:  # keep the loop alive
            print(f"[watcher] {type(e).__name__}: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:  # Ctrl+C / dev.py shutdown — exit quietly, no traceback
        pass
