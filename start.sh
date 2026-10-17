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

# 3. core deps (quiet, idempotent)
echo "  installing core dependencies…"
"$PIP" install -q --upgrade pip >/dev/null
"$PIP" install -q fastapi "uvicorn[standard]" httpx argon2-cffi faker

# 4. extra deps only for whichever integrations you turned on in .env
want() { grep -qiE "^$1=(0|false|no|off)\s*$" .env; }         # FAKE flag set to off
haskey() { grep -qiE "^$1=.+$" .env && ! grep -qiE "^$1=\s*$" .env; }  # key has a value
if want GMAIL_FAKE; then echo "  + Gmail libs…"; "$PIP" install -q google-api-python-client google-auth google-auth-oauthlib; fi
if want DAYTONA_FAKE; then echo "  + Daytona SDK…"; "$PIP" install -q daytona; fi
if haskey ANTHROPIC_API_KEY; then echo "  + Anthropic SDK…"; "$PIP" install -q anthropic; fi

echo "→ starting (Ctrl+C to stop)"
exec "$VENV/bin/python" dev.py
