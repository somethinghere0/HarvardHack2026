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
                                              ├─▶ Claude                (classify, reply, build identity)
                                              └─▶ Daytona sandbox ─▶ decoy portal
                                                     (agent: open portal, enter creds, relay OTP)
                                                           │
   portal performs the account takeover (login+OTP+drain) ▼
   proxy ─▶ Nessie v2 ─▶ /events ─▶ orchestrator ─▶ indicators + risk ─▶ fraud monitor
```

| Service | Dir | Role |
| --- | --- | --- |
| `proxy` | [`proxy/`](proxy/README.md) | Auth + Nessie gateway: holds the key, adds login + OTP, scopes each session to its own decoy customer, logs every request. |
| `backend` | `backend/` | Orchestrator: persona/engagement lifecycle, Claude (classify/reply/identity), OTP, the Nessie `/events` ingest + indicator engine, and the Daytona agent runner. Agent script in `backend/agent/`. |
| `portal` | `portal/` | The decoy "scammer" phishing site. Holds only phished credentials + OTP, and uses them to take over the Honeybank account and sweep it to a mule. |
| `frontend` | `frontend/` | `/` the bait bank, `/ops.html` the fraud monitor, `/portal` the phishing page. nginx routes `/bank-api`→proxy, `/api`→orchestrator, `/portal`→portal. |

## Keys you need (`.env`)

Copy `.env.example` to `.env` and fill in:

- **`NESSIE_API_KEY`** — https://v2.nessieisreal.com/ (required).
- **`ANTHROPIC_API_KEY`** — https://console.anthropic.com/ (required: classification, replies, identities, the agent).
- **`DAYTONA_API_KEY`** — https://www.daytona.io/ (required to run the agent). `DAYTONA_API_URL`/`DAYTONA_TARGET` stay blank for Cloud.
- **`PUBLIC_URL`** — a public tunnel back to this machine (required for the agent + webhooks). Quick tunnel:
  `cloudflared tunnel --url http://localhost:3000`, then paste the printed URL.
- **`GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD`** — a Gmail App Password (2-Step Verification →
  myaccount.google.com/apppasswords) for inbound mail and OTP/reply delivery. The OTP flow still works
  without Gmail (the agent reads the code from the orchestrator), but replies and real intake need it.
- **`INTERNAL_SECRET`** — any long random string.

## Run

```bash
cp .env.example .env     # fill in the keys above
cloudflared tunnel --url http://localhost:3000   # in a second terminal; put the URL in PUBLIC_URL
./start.sh               # creates the venv, installs deps, launches everything
```

- **Bank (bait):** http://localhost:3000/
- **Fraud monitor:** http://localhost:3000/ops.html — a status strip shows which integrations are live.
- **Decoy portal:** http://localhost:3000/portal

With Docker instead: `docker compose up --build` (same `.env`).

## How an engagement runs

1. A scam email arrives (Gmail watcher) or you POST one to `/api/sim/inbound-email`.
2. Claude classifies it; if it's a scam, the orchestrator builds a decoy persona — a Claude-invented
   identity, a Honeybank login, and a Nessie customer with seeded accounts — and drafts a reply.
3. The orchestrator launches a Daytona sandbox running the browser agent (`backend/agent/portal_agent.py`),
   which opens the portal, enters the decoy credentials, and relays the OTP it reads from the orchestrator.
4. The portal takes over the account through the proxy: login → OTP → sweep to a mule, in structuring-style
   chunks. Those transfers hit real Nessie.
5. The orchestrator ingests the transfers from Nessie's `/events` feed and scores the engagement; the
   fraud monitor shows the timeline, indicators, mule account, and risk.

Note: Nessie settles transactions asynchronously (seeded deposits take a bit to become spendable), which
is why the agent's sandbox-startup time is useful — funds are available by the time it drains.

## Tests

```bash
make test        # proxy auth tests + orchestrator indicator tests
```

Design notes: `.plans/`.
