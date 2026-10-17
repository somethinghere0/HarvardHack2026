from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    proxy_url: str = "http://proxy:8000"
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    poll_interval_s: int = 15
    quarantine_label: str = "Gateway/Quarantine"
    held_label: str = "Gateway/Held"
    scam_label: str = "Gateway/Scam"
    trusted_domains: tuple[str, ...] = ()
    daytona_api_key: str = ""
    daytona_api_url: str = ""
    proxy_username: str = ""
    proxy_password: str = ""
    canary_email_base: str = ""  # e.g. you@gmail.com -> decoy addresses you+<canary>@gmail.com
    evidence_dir: str = "/data/evidence"

    @property
    def gmail_configured(self) -> bool:
        return bool(self.gmail_client_id and self.gmail_client_secret and self.gmail_refresh_token)


def load_settings() -> Settings:
    env = os.environ.get
    return Settings(
        proxy_url=env("PROXY_URL", Settings.proxy_url),
        gmail_client_id=env("GMAIL_CLIENT_ID", ""),
        gmail_client_secret=env("GMAIL_CLIENT_SECRET", ""),
        gmail_refresh_token=env("GMAIL_REFRESH_TOKEN", ""),
        poll_interval_s=int(env("POLL_INTERVAL_S", Settings.poll_interval_s)),
        daytona_api_key=env("DAYTONA_API_KEY", ""),
        daytona_api_url=env("DAYTONA_API_URL", ""),
        proxy_username=env("PROXY_USERNAME", ""),
        proxy_password=env("PROXY_PASSWORD", ""),
        canary_email_base=env("CANARY_EMAIL_BASE", ""),
        evidence_dir=env("EVIDENCE_DIR", Settings.evidence_dir),
        trusted_domains=tuple(d.strip().lower() for d in env("TRUSTED_DOMAINS", "").split(",") if d.strip()),
    )
