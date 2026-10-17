# Honeybank

A fraud honeypot built on the Capital One **Nessie v2** sandbox. An inbound scam email spins up a
disposable decoy "victim" — a fictitious persona with a real-looking Nessie bank account — and lets
the scammer run their whole playbook against it. We watch from the inside and keep the two things a
bank can act on: **where the money goes** (the mule account) and **how it moves** (the behavioural
fingerprint). Everything is mock; no real money moves and no real person is involved.

## Pipeline

```
scam email ─▶ Gmail watcher ─▶ orchestrator ──┬─▶ proxy ─▶ Nessie v2   (decoy persona + accounts)
                                              ├─▶ Daytona sandbox       (decoy agent: reply, log in, relay OTP)
                                              └─▶ Honeybank (public URL) (the bait the scammer logs into)
                                                       │
   every login / transfer / payee is logged ──────────┘──▶ indicators + risk score ──▶ fraud monitor
```

| Service | Dir | Port | Role |
| --- | --- | --- | --- |
| `proxy` | [`proxy/`](proxy/README.md) | 8000 | Auth + Nessie gateway. Holds the API key, adds login + OTP, scopes each session to its own decoy customer, logs every request. |
| `backend` | `backend/` | 8001 | Orchestrator: persona/engagement lifecycle, Nessie webhook receiver + event timeline, indicator engine, OTP email, decoy agent runner. |
| `frontend` | `frontend/` | 3000 | `/` the bait bank (vanilla JS); `/ops.html` the fraud monitor. nginx routes `/bank-api`→proxy, `/api`→backend. |

## Run it locally — one command, no Docker, no keys

Every external service (Nessie, Gmail, Daytona, Photon, Anthropic) has a built-in **fake**, so the
whole thing runs offline. `start.sh` makes the virtualenv, installs deps, and creates `.env` on the
first run — just:

```bash
./start.sh
```

(or `make start`). Then open:

- **Bait bank** → http://localhost:3000/
- **Fraud monitor** → http://localhost:3000/ops.html — a status strip shows which services are live
  vs. faked. Click **Simulate scam + drain** to run the full pipeline (classify → build persona →
  decoy logs in, clearing OTP → scammer drains to a mule → indicators light up to risk 100).

`Ctrl+C` stops it; `make stop` frees the ports if a run gets stuck.

## Go live, one service at a time

Edit `.env` (don't put inline `# comments` after a value), flip a `FAKE` flag to `0`, fill its keys,
and re-run `./start.sh` — it installs that integration's extra deps automatically:

- **Nessie** (`NESSIE_FAKE=0`): get a key at https://v2.nessieisreal.com/. Amounts are integer cents.
- **Cloudflare tunnel**: Nessie webhooks need a public URL back to this machine. Quick tunnel:
  `cloudflared tunnel --url http://localhost:3000`, then put the printed URL in `PUBLIC_URL`. Without
  it the orchestrator falls back to polling `GET /events`.
- **Gmail** (`GMAIL_FAKE=0`): easiest is an **App Password** — enable 2-Step Verification, generate one
  at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), set `GMAIL_APP_PASSWORD`
  (SMTP/IMAP, no GCP project). Advanced: leave it blank to use OAuth via `python backend/scripts/gmail_authorize.py`.
  Either way, run `python backend/scripts/gmail_watcher.py` to feed real inbound mail. Personas use `+`
  sub-addressing (`you+persona_<id>@gmail.com`) so everything lands in one inbox.
- **Daytona** (`DAYTONA_FAKE=0`): one disposable sandbox per engagement for the browser agent
  (https://www.daytona.io/docs/). The browser-automation script is a marked scaffold in `daytona_runner.py`.
- **Photon / Anthropic**: optional synthetic identities and LLM classification/replies; both fall back
  to local logic when unset.

## Run with Docker (live Nessie)

```bash
cp .env.example .env     # set NESSIE_API_KEY, NESSIE_FAKE=0, PUBLIC_URL, INTERNAL_SECRET
docker compose up --build
```

Then the bank is at http://localhost:3000/ and the monitor at http://localhost:3000/ops.html.

## Tests

```bash
cd proxy   && pip install -r requirements.txt pytest && python -m pytest    # auth proxy
cd backend && python -m pytest tests                                        # indicator engine
```

Design notes: `.plans/`.
