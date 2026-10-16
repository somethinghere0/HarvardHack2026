from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    nessie_api_key: str
    nessie_base_url: str = "https://v2-prod-api.nessieisreal.com"
    session_ttl_hours: int = 12
    db_path: str = "/data/proxy.db"
    auth_rate_limit: int = 10  # attempts per window, per client IP
    auth_rate_window_s: int = 60


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
    )
