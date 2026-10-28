"""Orchestrator settings, all from environment. Every integration is live — there are no fake
fallbacks; a missing key makes the feature that needs it error clearly."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = os.environ.get("ORCH_DB_PATH", "/data/orchestrator.db")

    # Auth proxy (used to create personas and seed their accounts through the real auth path).
    proxy_url: str = os.environ.get("PROXY_URL", "http://proxy:8000")

    # Shared secret for proxy<->orchestrator and agent<->orchestrator internal calls.
    internal_secret: str = os.environ.get("INTERNAL_SECRET", "dev-internal-secret")

    # Public base URL (Cloudflare tunnel). It is Honeybank's own address — the phishing destination
    # the agent signs into — plus the Nessie webhook callback. Blank => poll GET /events for webhooks.
    public_url: str = os.environ.get("PUBLIC_URL", "").rstrip("/")

    # This orchestrator's own address as seen from this machine (the local agent runtime reports here).
    local_url: str = os.environ.get("ORCH_LOCAL_URL", "http://127.0.0.1:8001").rstrip("/")
    # The bank frontend as seen from this machine (used when there's no PUBLIC_URL).
    local_bank_url: str = os.environ.get("LOCAL_BANK_URL", "http://127.0.0.1:3000").rstrip("/")

    # Where the decoy agent runs: auto (Daytona if the sandbox can reach PUBLIC_URL, else local),
    # daytona, or local.
    agent_runtime: str = os.environ.get("AGENT_RUNTIME", "auto").strip().lower() or "auto"
    # Every inbound email is detonated in its own sandbox; this caps how many run at once.
    max_detonations: int = int(os.environ.get("MAX_DETONATIONS", "3"))
    # After the agent finishes, how long to wait for Nessie's transfer events to land before judging.
    verdict_grace_seconds: float = float(os.environ.get("VERDICT_GRACE_SECONDS", "8"))
    # If the proxy saw the decoy submit a transfer, keep re-reading the ledger this long for Nessie to
    # record it before judging (its transfer events have trailed the POST by 40s+).
    ledger_confirm_seconds: float = float(os.environ.get("LEDGER_CONFIRM_SECONDS", "120"))

    # Nessie v2 (shared with the proxy).
    nessie_base_url: str = os.environ.get("NESSIE_BASE_URL", "https://v2-prod-api.nessieisreal.com").rstrip("/")
    nessie_api_key: str = os.environ.get("NESSIE_API_KEY", "").strip()
    nessie_webhook_secret: str = os.environ.get("NESSIE_WEBHOOK_SECRET", "").strip()

    # Gmail (single real inbox; personas are sub-addressed inbox+persona_<id>@gmail.com). App password
    # (SMTP/IMAP) if set, else OAuth user credentials.
    gmail_address: str = os.environ.get("GMAIL_ADDRESS", "").strip()
    gmail_app_password: str = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    gmail_credentials_file: str = os.environ.get("GMAIL_CREDENTIALS_FILE", "./secrets/gmail_oauth.json")
    gmail_token_file: str = os.environ.get("GMAIL_TOKEN_FILE", "./secrets/gmail_token.json")

    # Email-firewall behaviour. The watcher reads from gmail_source_label (INBOX, or a holding label
    # fed by a Gmail filter for true pre-inbox vetting), labels each email Safe/Scam, and — only if
    # gmail_archive_scams is on — removes scams from the inbox (archive, never trash; reversible).
    gmail_source_label: str = os.environ.get("GMAIL_SOURCE_LABEL", "INBOX")
    gmail_quarantine_label: str = os.environ.get("GMAIL_QUARANTINE_LABEL", "Honeybank/Quarantine")
    gmail_safe_label: str = os.environ.get("GMAIL_SAFE_LABEL", "Honeybank/Safe")
    gmail_archive_scams: bool = os.environ.get("GMAIL_ARCHIVE_SCAMS", "0").strip().lower() in ("1", "true", "yes", "on")
    # Mail this system sends to itself (OTP codes to persona sub-addresses) is back-channel traffic
    # between the bank and a sandbox, not something the inbox owner should see. The watcher files it
    # under gmail_internal_label and archives it out of the inbox unless this is turned off.
    gmail_internal_label: str = os.environ.get("GMAIL_INTERNAL_LABEL", "Honeybank/Internal")
    gmail_hide_internal_mail: bool = os.environ.get("GMAIL_HIDE_INTERNAL_MAIL", "1").strip().lower() in ("1", "true", "yes", "on")

    # Daytona (one disposable sandbox per engagement for the decoy agent).
    daytona_api_key: str = os.environ.get("DAYTONA_API_KEY", "").strip()
    daytona_api_url: str = os.environ.get("DAYTONA_API_URL", "").strip()
    daytona_target: str = os.environ.get("DAYTONA_TARGET", "").strip()

    # Anthropic (classification, replies, synthetic identities, and the agent's brain).
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    anthropic_model: str = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5").strip()

    otp_ttl_seconds: int = int(os.environ.get("OTP_TTL_SECONDS", "300"))

    # The bank's per-transfer ceiling (the proxy enforces it; shown in the playbook). Same env var.
    transfer_limit_cents: int = int(os.environ.get("TRANSFER_LIMIT_CENTS", "500000"))
    # Bank-wide screening: every pending transfer under this key is checked against the mule
    # watchlist the honeypot builds. With a public URL that's a Nessie decision hook (declined
    # before it settles); otherwise the poller cancels it inside the pending window.
    watchlist_block: bool = os.environ.get("WATCHLIST_BLOCK", "1").strip().lower() in ("1", "true", "yes", "on")

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise RuntimeError("missing required config: " + ", ".join(missing))


def settings() -> Settings:
    return Settings()
