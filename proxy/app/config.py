from __future__ import annotations

import os
from dataclasses import dataclass


def _b(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    nessie_api_key: str
    nessie_base_url: str = "https://v2-prod-api.nessieisreal.com"
    session_ttl_hours: int = 12
    db_path: str = "/data/proxy.db"
    auth_rate_limit: int = 10  # attempts per window, per client IP
    auth_rate_window_s: int = 60

    # Honeypot additions (all default off so the proxy still works standalone).
    # OTP step on login: login returns {otp_required, challenge_id}; /auth/verify-otp exchanges the
    # emailed code for a token. The orchestrator sends the email.
    otp_required: bool = False
    otp_ttl_seconds: int = 300
    # Restrict a session to its own customer's resources, so a logged-in scammer can't enumerate the
    # other decoy customers (which would blow the cover).
    enforce_customer_scope: bool = False
    # Orchestrator for OTP email + request/login telemetry. Empty disables those calls.
    orchestrator_url: str = ""
    internal_secret: str = "dev-internal-secret"


def load_settings() -> Settings:
    key = os.environ.get("NESSIE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("NESSIE_API_KEY is required")
    return Settings(
        nessie_api_key=key,
        nessie_base_url=os.environ.get("NESSIE_BASE_URL", Settings.nessie_base_url).rstrip("/"),
        session_ttl_hours=int(os.environ.get("SESSION_TTL_HOURS", Settings.session_ttl_hours)),
        db_path=os.environ.get("DB_PATH", Settings.db_path),
        auth_rate_limit=int(os.environ.get("AUTH_RATE_LIMIT", Settings.auth_rate_limit)),
        auth_rate_window_s=int(os.environ.get("AUTH_RATE_WINDOW_S", Settings.auth_rate_window_s)),
        otp_required=_b("OTP_REQUIRED", Settings.otp_required),
        otp_ttl_seconds=int(os.environ.get("OTP_TTL_SECONDS", Settings.otp_ttl_seconds)),
        enforce_customer_scope=_b("ENFORCE_CUSTOMER_SCOPE", Settings.enforce_customer_scope),
        orchestrator_url=os.environ.get("ORCHESTRATOR_URL", Settings.orchestrator_url).rstrip("/"),
        internal_secret=os.environ.get("INTERNAL_SECRET", Settings.internal_secret),
    )
