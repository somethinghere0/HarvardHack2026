#!/usr/bin/env bash
# One-click Honeybank. Creates the virtualenv, installs deps, makes .env on first run, and launches
# the whole stack. Safe to run repeatedly. No arguments needed.
#
#   ./start.sh
#
# Then open http://localhost:3000/ (bank) and http://localhost:3000/ops.html (fraud monitor).
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
VENV=".venv"
PIP="$VENV/bin/pip"

echo "→ Honeybank setup"

# 1. virtualenv
if [ ! -x "$VENV/bin/python" ]; then
  echo "  creating virtualenv (.venv)…"
  "$PY" -m venv "$VENV"
fi

# 2. .env on first run
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  created .env from .env.example (all services faked — edit it to go live)"
fi

# 3. core deps (quiet, idempotent) — everything is live, so Claude is always needed
echo "  installing dependencies…"
"$PIP" install -q --upgrade pip >/dev/null
"$PIP" install -q fastapi "uvicorn[standard]" httpx argon2-cffi python-multipart anthropic

# 4. integration deps based on .env (non-fatal: a failed optional install shouldn't stop startup)
haskey() { grep -qE "^$1=[^[:space:]]" .env; }
if haskey DAYTONA_API_KEY; then echo "  + Daytona SDK…"; "$PIP" install -q daytona || echo "    (Daytona SDK install failed; the agent won't run)"; fi
if ! haskey GMAIL_APP_PASSWORD && haskey GMAIL_ADDRESS; then echo "  + Gmail OAuth libs…"; "$PIP" install -q google-api-python-client google-auth google-auth-oauthlib || echo "    (Gmail OAuth libs failed; use an App Password instead)"; fi

echo "→ starting (Ctrl+C to stop)"
exec "$VENV/bin/python" dev.py
