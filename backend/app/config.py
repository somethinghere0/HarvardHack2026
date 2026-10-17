"""Orchestrator settings, all from environment. Every external service has a FAKE fallback so the
whole system runs locally without Docker or real API keys (demo-safe, nothing real moves)."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _b(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # Where the orchestrator stores engagements/events/otps/emails.
    db_path: str = os.environ.get("ORCH_DB_PATH", "/data/orchestrator.db")

    # The auth proxy (used to create personas and seed their accounts through the real auth path).
    proxy_url: str = os.environ.get("PROXY_URL", "http://proxy:8000")

    # Shared secret for proxy -> orchestrator internal calls (OTP email, proxy request logs).
    internal_secret: str = os.environ.get("INTERNAL_SECRET", "dev-internal-secret")

    # Public base URL (Cloudflare tunnel) used to build the Nessie webhook callback. Blank disables
    # webhook registration (the orchestrator then relies on GET /events polling instead).
    public_url: str = os.environ.get("PUBLIC_URL", "").rstrip("/")

    # Nessie (admin-level, for webhook registration + the /events feed). Shares the proxy's key.
    nessie_base_url: str = os.environ.get("NESSIE_BASE_URL", "https://v2-prod-api.nessieisreal.com").rstrip("/")
    nessie_api_key: str = os.environ.get("NESSIE_API_KEY", "").strip()
    nessie_webhook_secret: str = os.environ.get("NESSIE_WEBHOOK_SECRET", "").strip()

    # Fake toggles (default on when no credentials are present).
    nessie_fake: bool = _b("NESSIE_FAKE", "1" if not os.environ.get("NESSIE_API_KEY", "").strip() else "0")
    gmail_fake: bool = _b("GMAIL_FAKE", "1")
    daytona_fake: bool = _b("DAYTONA_FAKE", "1")
    photon_fake: bool = _b("PHOTON_FAKE", "1")

    # Gmail (the single real inbox; personas are sub-addressed as inbox+persona_<id>@gmail.com).
    gmail_address: str = os.environ.get("GMAIL_ADDRESS", "you@example.com")
    gmail_credentials_file: str = os.environ.get("GMAIL_CREDENTIALS_FILE", "./secrets/gmail_oauth.json")
    gmail_token_file: str = os.environ.get("GMAIL_TOKEN_FILE", "./secrets/gmail_token.json")

    # Daytona (one disposable sandbox per engagement for the decoy agent).
    daytona_api_key: str = os.environ.get("DAYTONA_API_KEY", "").strip()
    daytona_api_url: str = os.environ.get("DAYTONA_API_URL", "").strip()
    daytona_target: str = os.environ.get("DAYTONA_TARGET", "").strip()

    # Photon (optional synthetic identities for personas; Faker is the fallback).
    photon_api_key: str = os.environ.get("PHOTON_API_KEY", "").strip()
    photon_api_url: str = os.environ.get("PHOTON_API_URL", "https://api.photon.example/v1").rstrip("/")

    # Anthropic (the decoy agent that reads threads and replies).
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    anthropic_model: str = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

    # OTP delivery: "email" (sent to the persona inbox, read back by the agent) or "direct"
    # (agent reads the code straight from the orchestrator — a stage fallback if email is slow).
    otp_mode: str = os.environ.get("OTP_MODE", "email")
    otp_ttl_seconds: int = int(os.environ.get("OTP_TTL_SECONDS", "300"))


def settings() -> Settings:
    return Settings()
