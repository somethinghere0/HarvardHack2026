# Bank of USA · Scam Tracker

**An email firewall that doesn't classify scams. It proves them.**

Every inbound email is held and *detonated*: a disposable decoy victim (a Claude-invented identity with
a real, funded account on the Capital One **Nessie v2** sandbox) does exactly what the email says, in a
real browser, inside a throwaway **Daytona** sandbox. If complying cost the decoy money or secrets, the
email is a scam and is quarantined. If it complied fully and lost nothing, the email is safe and
delivered. The verdict comes from what happened, not from how the email reads.

A scam engagement then stays **armed**. When the scammer comes back and uses the phished login, that
sign-in is a canary that upgrades the verdict from *likely* to *confirmed*, and every move they make
inside the decoy is recorded as an account-takeover **playbook**. The mule account they drained to goes
on a bank-wide **watchlist**, and Nessie's decision hook lets us decline any ordinary customer's transfer
to that mule before it settles. Everything is mock money in a sandbox. No real person is involved.

Built at HarvardHack 2026 (Oct 17–18, 2026). Internal codename: *Honeybank*.

## Pipeline

```
scam email ─▶ Gmail watcher ─▶ orchestrator ──┬─▶ Claude          extract what the email asks for
                                              ├─▶ proxy ─▶ Nessie  decoy persona + funded accounts
                                              └─▶ Daytona / host   browser agent plays the victim
                                                        │
                       agent opens the link, signs in, clears the OTP, sends the money
                                                        ▼
       proxy ─▶ Nessie ─▶ webhooks + /events ─▶ outcome ─▶ verdict (scam · safe · review)
                                                        │
                   armed decoy ─▶ canary login ─▶ playbook ─▶ watchlist ─▶ decision hook declines
```

| Service | Dir | Role |
| --- | --- | --- |
| `proxy` | [`proxy/`](proxy/README.md) | Auth + Nessie gateway. Holds the Nessie key, adds username/password login and a one-time-code second factor, scopes every session to its own customer, enforces the per-transfer limit, and attributes every request to a session and an actor (`agent` or `external`). |
| `backend` | `backend/` | Orchestrator: email intake, decoy persona lifecycle, the agent runner, Nessie event ingest, the outcome judge, indicators, playbook, intel (watchlist, crews, money flow), scam memory, and the scenario swarm. The agents live in `backend/agent/`. |
| `frontend` | `frontend/` | `/` is Bank of USA, a working retail bank over Nessie. `/ops.html` is the Scam Tracker. nginx (or `dev_gateway.py` locally) routes `/bank-api` to the proxy and `/api` to the orchestrator. |
| `email-generator` | `email-generator/` | Static page for judges and demo visitors: compose a scam email aimed at the bank and send it to the watched inbox. Deployed at https://harvardhack2026-email-generator.vercel.app/. |

The decoy agent has two drivers, chosen with `AGENT_DRIVER`: `dom` (default, `backend/agent/bank_agent.py`)
reads the page and emits JSON actions; `computer_use` (experimental, `backend/agent/cu_agent.py`) drives a
real screen with Claude's computer-use toolset.

## Keys you need (`.env`)

Copy `.env.example` to `.env` and fill in:

- **`NESSIE_API_KEY`** from https://v2.nessieisreal.com/ (required).
- **`ANTHROPIC_API_KEY`** from https://console.anthropic.com/ (required: email extraction, identities, the agent's brain).
- **`DAYTONA_API_KEY`** from https://www.daytona.io/ (required to run the agent in a sandbox). `DAYTONA_API_URL` and `DAYTONA_TARGET` stay blank for Cloud.
- **ngrok** for the public tunnel (the bank link in the scam email, Nessie webhooks, the decision hook). One time: `brew install ngrok && ngrok config add-authtoken <token>`, then claim a free static domain at dashboard.ngrok.com/domains and put it in **`NGROK_DOMAIN`**. `dev.py` starts or reuses ngrok and passes the live URL to the orchestrator as `PUBLIC_URL`.
- **`GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD`**, a Gmail App Password (2-Step Verification → myaccount.google.com/apppasswords) for inbound mail and OTP delivery. Enable IMAP in Gmail settings.
- **`INTERNAL_SECRET`**, any long random string.

Everything is live. Each feature needs its real key; there is no offline or mock mode.

## Run

```bash
cp .env.example .env     # fill in the keys above
./start.sh               # venv, deps, Chromium, ngrok, proxy, orchestrator, watcher, gateway
```

- **Bank of USA:** http://localhost:3000/
- **Scam Tracker:** http://localhost:3000/ops.html (a status strip shows which integrations are live)
- **Public URL:** printed in the startup log. That is the link that goes in the scam email.

With Docker: `docker compose up --build` (same `.env`).

**Where the agent runs (`AGENT_RUNTIME=auto`).** Daytona Tier 1/2 sandboxes only reach an egress
allowlist (package registries, AI APIs), not ngrok or cloudflared tunnels. In `auto`, the runner probes
the sandbox's route to `PUBLIC_URL`. If it is blocked, it discards the sandbox and runs the same agent
on this machine in headless Chromium, and the Scam Tracker says so in its terminal. On Tier 3+ the
probe passes and the agent runs in the sandbox. Force either with `AGENT_RUNTIME=daytona|local`.

## How an engagement runs

1. **Intake.** An email arrives through the Gmail watcher (`backend/scripts/gmail_watcher.py`), or you
   POST one to `/api/sim/inbound-email`, or you click `./simulate --drain` on the tracker. Every email
   is held as `pending`. None is judged by its wording. A detonation interrupted by a restart is resumed.
2. **Extraction.** Claude lists what the email asks the reader to do (links to open, places to sign in,
   money to send, codes to hand over). This briefs the victim. It is not the verdict.
3. **Decoy persona.** The orchestrator builds a victim: a Claude-invented identity, a Bank of USA login
   created through the proxy's real signup path, and a Nessie customer with checking, savings, and a
   credit card, seeded with payroll and transfer history so it does not look brand new.
4. **Detonation.** The browser agent (`backend/agent/bank_agent.py`, Playwright + Claude) plays the
   recipient and does exactly what the email says: opens the link, signs in where told, reads the
   one-time code from the decoy's inbox and enters it, and sends money where told. Credentials never
   enter the prompt. Claude types placeholders and the agent substitutes the real values, reporting any
   secret that lands on a page outside the decoy's own bank (or in a drafted reply) as disclosed.
5. **Verdict.** `backend/app/outcome.py` reads the engagement's event timeline. Money that left the
   decoy, or decoy secrets that left the bank, mean **scam** (quarantined). Full compliance with nothing
   lost means **safe** (delivered). A run that did not finish is held for **review**. The judge waits for
   Nessie's ledger to confirm submitted transfers, so a drain the ledger records late cannot be called
   safe, and the watcher relabels a message if a late transfer flips the verdict.
6. **Armed.** A scam engagement stays live: the decoy account and its credentials keep working. The
   agent marks its own requests with an `X-Decoy-Agent` header. Any sign-in to the decoy without it is
   a third party holding the phished password. That canary (`credential.used_by_third_party`) upgrades
   the verdict from **scam · likely** to **scam · confirmed**: proof from outside the sandbox, not inference.

## Tripwires, the playbook, and what the bank gets back

Once someone is inside the decoy, every move is a bank operation through the proxy, and the proxy
attributes every one to a session and an actor. The decoy is shaped to ask questions of whoever breaks in:

- **Three products** (checking, savings, a credit card), with savings holding more than checking. Do
  they sweep savings first? Do they try a cash advance?
- **A $5,000 per-transfer limit** (`TRANSFER_LIMIT_CENTS`, enforced by the proxy and declined before it
  reaches the ledger). Do they probe it and then structure underneath it?
- **Editable contact details** (`/auth/profile`; the email address is where one-time codes go). Do they
  lock the victim out before or after the drain, and what address do they redirect to?

`backend/app/playbook.py` turns the attributed timeline into the account-takeover kill chain
(access → recon → lockout → drain → cash-out) with timing from login to first move, recon reads,
declines, structuring, an op-sequence fingerprint, and a coarse operator profile: scripted drain,
organised account-takeover crew, experienced casher, or opportunist. `backend/app/indicators.py` scores
the same timeline into a 0–100 risk score with labelled indicators.

`backend/app/intel.py` turns that into things a bank can act on:

- **Mule watchlist.** Every account a scam sent money to, plus the layer it fanned out to after
  `./simulate --launder`. With a public URL the orchestrator registers a **Nessie decision hook**. Nessie
  asks before any transfer settles. Decoys are approved (letting them be drained is the point). An
  ordinary customer paying a watchlisted account is **declined before the money moves**, with the
  engagement that found the mule as the reason. Without a public URL the `/events` poller cancels the
  hit inside the pending window. Watchlisted accounts paying each other are watched, not frozen, so the
  network stays visible. `./simulate --customer-pays-mule` on the tracker demonstrates it.
- **Crews.** Engagements linked by the same mule, the same sender, or the same playbook fingerprint
  (`/api/intel/crews`). A decoy paying a mule another engagement already found is confirmed on the spot.
- **Money flow.** `/api/engagements/{id}/flow` follows the money past the mule, live from Nessie, and
  the tracker draws decoy → mule → layer → cash.
- **Scam memory.** `backend/app/memory.py` builds one dossier per scam ever detonated (lure themes,
  sender domain, phishing host, how the money moved, who received it, how the operator behaved) and the
  cross-scam patterns: the same themes, domains, hosts, mules, and fingerprints showing up again.

## The Scam Tracker

`/ops.html` has three views:

- **Monitor.** Every inbound email and its verdict, the engagement detail (live terminal, the agent's
  actual browser frames, timeline, indicators, verdict evidence, the ARMED card with the decoy's
  credentials, the playbook, the money flow), and the bank-wide mule watchlist with its interdictions.
- **Scenario swarm.** Nessie is the bank *and* the source of the fraud: for each of eight scam types
  (account takeover, large transfer to a new payee, card testing, structuring, velocity spike, foreign
  ATM cash-out, geo-distant purchase, unusual category) Nessie's traffic simulator generates a bank's
  worth of transactions with that anomaly planted. Every customer becomes a case in its own Daytona
  sandbox running a rules detector (`backend/agent/detector.py`) that escalates only borderline
  transactions to Claude. The view scores what was flagged against Nessie's planted count, with a clean
  control run for false positives, and streams the live Nessie API log.
- **Scam memory.** The dossiers and patterns above, searchable.

Nessie settles transactions asynchronously, so seeded deposits take a moment to become spendable. The
runner waits for the decoy to be funded before the agent starts.

## Tests

```bash
make test        # 23 tests: proxy auth/OTP/scope/limit (10); indicators, outcome ledger lag, playbook, canary + decision hook (13)
```

Design notes for the proxy: `.plans/`. Demo run-of-show: [`docs/DEMO.md`](docs/DEMO.md). Devpost text:
[`docs/DEVPOST.md`](docs/DEVPOST.md). Video script: [`docs/VIDEO_SCRIPT.md`](docs/VIDEO_SCRIPT.md).
