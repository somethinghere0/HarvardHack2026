# Honeybank

A fraud honeypot on the Capital One **Nessie v2** sandbox. An inbound scam email spins up a disposable
decoy "victim" — a fictitious persona with a real-looking Nessie bank account — then a real agent in a
sandbox plays the victim: it replies to the scammer, logs into the scammer's portal with the decoy
credentials, and relays the one-time code. The scammer drains the decoy account, and we keep the two
things a bank can act on: **where the money went** (the mule account) and **how it moved** (the
behavioural fingerprint). Everything is mock money in a sandbox; no real person is involved.

Everything is **live** — each feature needs its real API key. There is no fake/offline mode.

## Pipeline

```
scam email ─▶ Gmail watcher ─▶ orchestrator ──┬─▶ proxy ─▶ Nessie v2   (decoy persona + seeded accounts)
                                              ├─▶ Claude                (read email, build identity)
                                              └─▶ Daytona sandbox ─▶ decoy portal
                                                     (agent: open portal, enter creds, relay OTP)
                                                           │
   portal performs the account takeover (login+OTP+drain) ▼
   proxy ─▶ Nessie v2 ─▶ /events ─▶ orchestrator ─▶ indicators + risk ─▶ fraud monitor
```

| Service | Dir | Role |
| --- | --- | --- |
| `proxy` | [`proxy/`](proxy/README.md) | Auth + Nessie gateway: holds the key, adds login + OTP, scopes each session to its own decoy customer, logs every request. |
| `backend` | `backend/` | Orchestrator: persona/engagement lifecycle, Claude (instruction extraction/identity), OTP, the Nessie `/events` ingest + indicator engine, and the Daytona agent runner. Agent script in `backend/agent/`. |
| `portal` | `portal/` | The decoy "scammer" phishing site. Holds only phished credentials + OTP, and uses them to take over the Honeybank account and sweep it to a mule. |
| `frontend` | `frontend/` | `/` the bait bank, `/ops.html` the fraud monitor, `/portal` the phishing page. nginx routes `/bank-api`→proxy, `/api`→orchestrator, `/portal`→portal. |

## Keys you need (`.env`)

Copy `.env.example` to `.env` and fill in:

- **`NESSIE_API_KEY`** — https://v2.nessieisreal.com/ (required).
- **`ANTHROPIC_API_KEY`** — https://console.anthropic.com/ (required: email extraction, identities, the agent).
- **`DAYTONA_API_KEY`** — https://www.daytona.io/ (required to run the agent). `DAYTONA_API_URL`/`DAYTONA_TARGET` stay blank for Cloud.
- **ngrok** — the public tunnel (bait-site link, Nessie webhooks). One-time: `brew install ngrok &&
  ngrok config add-authtoken <token>`, and claim your free static domain at dashboard.ngrok.com/domains
  → put it in **`NGROK_DOMAIN`**. `dev.py` starts (or reuses) ngrok and passes the live URL to the
  orchestrator as `PUBLIC_URL`, so nothing goes stale between runs.
- **`GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD`** — a Gmail App Password (2-Step Verification →
  myaccount.google.com/apppasswords) for inbound mail and OTP/reply delivery. The OTP flow still works
  without Gmail (the agent reads the code from the orchestrator), but replies and real intake need it.
- **`INTERNAL_SECRET`** — any long random string.

## Run

```bash
cp .env.example .env     # fill in the keys above
./start.sh               # creates the venv, installs deps + Chromium, starts ngrok, launches everything
```

- **Bank (bait):** http://localhost:3000/
- **Fraud monitor:** http://localhost:3000/ops.html — a status strip shows which integrations are live.
- **Decoy portal:** http://localhost:3000/portal
- **Public:** the startup log prints the ngrok URL — that's the link to put in the scam email.

**Where the agent runs (`AGENT_RUNTIME=auto`).** Daytona's Tier 1/2 sandboxes can only reach an
egress allowlist (PyPI, AI APIs, …) — not ngrok or cloudflared tunnels. In `auto`, the runner probes
the sandbox's route to `PUBLIC_URL`; if it's blocked, it discards the sandbox and runs the same agent
on this machine in headless Chromium (the Scam Tracker says so in its terminal). On Tier 3+ the probe
passes and the agent runs in the sandbox. Force either with `AGENT_RUNTIME=daytona|local`.

With Docker instead: `docker compose up --build` (same `.env`).

## How an engagement runs

1. An email arrives (Gmail watcher) or you POST one to `/api/sim/inbound-email`. **Every** email is
   held; none is judged by how it reads.
2. Claude extracts what the email asks the reader to do (links, sign-ins, transfers, codes to hand
   over), and the orchestrator builds a decoy persona: a Claude-invented identity, a Bank of USA login,
   and a Nessie customer with funded accounts.
3. A sandboxed browser agent (`backend/agent/bank_agent.py`) plays the recipient and does exactly what
   the email says. It opens the link, signs in where told, enters the OTP from the decoy's inbox, and
   sends money where told. Credentials are typed as placeholders, and any that land outside the decoy's
   own bank (or in a drafted reply) are reported as disclosed.
4. The verdict comes from the outcome (`backend/app/outcome.py`). Money that left the decoy, or decoy
   secrets that left the bank, mean **scam** (quarantined). Full compliance with nothing lost means
   **safe** (delivered). A run that didn't finish is held for **review**.
5. Transfers are ingested from Nessie's webhook / `/events` feed and scored; the Scam Tracker shows
   the timeline, the agent's browser, indicators, mule account, and verdict evidence.

Note: Nessie settles transactions asynchronously (seeded deposits take a bit to become spendable), which
is why the agent's sandbox-startup time is useful — funds are available by the time it drains.

## Tests

```bash
make test        # proxy auth tests + orchestrator indicator tests
```

Design notes: `.plans/`.
