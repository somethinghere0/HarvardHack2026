"""One-time Gmail OAuth: turns your downloaded OAuth client file into a saved user-token file the
orchestrator reuses. Run locally (it opens a browser):

    python backend/scripts/gmail_authorize.py

Needs GMAIL_CREDENTIALS_FILE (the client secret JSON from Google Cloud) and writes GMAIL_TOKEN_FILE.
Create an OAuth client of type "Desktop app" in Google Cloud, enable the Gmail API, and add your
address as a test user on the consent screen."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.config import settings  # noqa: E402
from app.gmail_client import GMAIL_SCOPES  # noqa: E402


def main() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    s = settings()
    if not os.path.exists(s.gmail_credentials_file):
        raise SystemExit(f"Missing {s.gmail_credentials_file} — download your OAuth client JSON there first.")
    flow = InstalledAppFlow.from_client_secrets_file(s.gmail_credentials_file, GMAIL_SCOPES)
    creds = flow.run_local_server(port=0)
    os.makedirs(os.path.dirname(os.path.abspath(s.gmail_token_file)), exist_ok=True)
    with open(s.gmail_token_file, "w") as f:
        f.write(creds.to_json())
    print(f"Saved token to {s.gmail_token_file}. Set GMAIL_FAKE=0 to use real Gmail.")


if __name__ == "__main__":
    main()
