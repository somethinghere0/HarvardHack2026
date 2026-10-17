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

    # Daytona (one disposable sandbox per engagement for the decoy agent).
    daytona_api_key: str = os.environ.get("DAYTONA_API_KEY", "").strip()
    daytona_api_url: str = os.environ.get("DAYTONA_API_URL", "").strip()
    daytona_target: str = os.environ.get("DAYTONA_TARGET", "").strip()

    # Anthropic (classification, replies, synthetic identities, and the agent's brain).
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    anthropic_model: str = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5").strip()

    otp_ttl_seconds: int = int(os.environ.get("OTP_TTL_SECONDS", "300"))

    def require(self, *names: str) -> None:
        missing = [n for n in names if not getattr(self, n)]
        if missing:
            raise RuntimeError("missing required config: " + ", ".join(missing))


def settings() -> Settings:
    return Settings()
