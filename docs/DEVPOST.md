# Bank of USA — Scam Tracker

An email firewall that lets scammers scam a fake bank, and records exactly how they do it.

## Inspiration

Every day, phishing emails land in millions of inboxes: "unusual activity on your account —
verify now." Spam filters either delete them (and we learn nothing) or miss them (and someone gets
robbed). We wanted a third option: **let the scam run — against a decoy — and capture the whole
attack.** Instead of guessing whether an email is dangerous from its text, we send a believable
"victim" to do exactly what the scammer wants, inside a throwaway sandbox, and watch what happens to
the money. The scammer gets a fake account; we get the two things a real bank can act on — **where
the money went** and **how it moved**.

## What it does

**Bank of USA** is a fully working online bank (sign-in, one-time-code login, checking/savings,
transfers) backed by the Capital One **Nessie** sandbox — every balance and transaction is real
Nessie data.

**Scam Tracker** is the firewall and command center:

1. **Vets every inbound email.** A watcher reads the Gmail account over IMAP and sends each new
   message to the orchestrator, which classifies it with Claude. Safe mail is delivered and labeled;
   scams are quarantined out of the inbox — and surfaced on the dashboard.
2. **Falls for the scam, on purpose.** For a credential-phishing email, the system creates a decoy
   persona — a Claude-invented identity with a real Nessie bank account seeded with believable
   history — then spins up a disposable **Daytona** sandbox running a real browser agent.
3. **Watches the attack happen.** The agent (Playwright + Claude) opens the link from the scam email,
   signs into the decoy account, reads the one-time code from the "victim's" inbox and enters it, and
   lets the account be drained to the scammer's mule account — all on real Nessie transactions.
4. **Turns it into intel.** Every login, payee, and transfer streams back to a dark, terminal-style
   dashboard: a live view of the sandbox (streaming terminal + the agent's actual browser), a
   fraud-indicator score (structuring, rapid drain, external payee, full drain…), the captured mule
   account, and the full timeline.

## How we built it

- **Capital One Nessie v2** — the bank's data layer. Real customers, accounts (in cents),
  deposits/transfers, the `/events` feed, and webhooks. Bank of USA is a thin, beautiful UI over it.
- **Auth proxy (FastAPI)** — holds the Nessie key server-side, adds username/password login, a
  one-time-code second factor, per-customer scoping (so a logged-in scammer can't enumerate other
  decoys), and request logging.
- **Orchestrator (FastAPI)** — the brain: email vetting, decoy-persona lifecycle, OTP, the Nessie
  event ingest + indicator engine, and the sandbox-agent runner.
- **Claude (Anthropic)** — classifies emails, invents the synthetic victim identities, and is the
  agent's decision loop inside the sandbox.
- **Daytona** — a fresh, disposable sandbox per engagement (every scammer gets a throwaway victim
  machine) running headless Chromium + Playwright.
- **Gmail (IMAP/SMTP via an app password)** — reads inbound mail and delivers one-time codes; no GCP
  project required.
- **Cloudflare Tunnel** — exposes the bank publicly so the sandboxed agent and Nessie webhooks can
  reach it.
- **Frontend** — vanilla JS, no build step: a Bank-of-America-style retail bank and a dark
  "hacker"-themed Scam Tracker with a live Daytona container viewer.

## Challenges we ran into

- **Nessie's real shape.** List endpoints return `{items}`, the event feed is `{items, next_cursor}`
  with the transaction nested under `data.transaction`, amounts are integer cents, and transactions
  **settle asynchronously** (balances lag ~seconds, so `available_cents` matters). We only found this
  by probing the live sandbox and fixing our assumptions.
- **Driving a real bank with an LLM.** The agent reads the page's fields and decides each action, so
  it works on login forms, OTP steps, and the transfer screen without hardcoded selectors.
- **Making it safe to demo.** Original "Bank of USA" branding, non-destructive Gmail actions (label,
  never trash), per-session scoping, and everything on a sandbox — no real money, no real person.

## Accomplishments we're proud of

- A genuinely end-to-end attack: email → classification → decoy account → sandboxed agent → real
  Nessie drain → fraud score, verified against the live Nessie API (risk 100/100).
- A demo you can *watch*: the Scam Tracker shows the Daytona container working in real time.
- An email firewall that actually acts on your inbox — safe mail through, scams quarantined.

## What's next

- A feed of fresh **mule accounts** and scammer fingerprints banks could subscribe to.
- Prebuilt Daytona snapshots for instant agent startup.
- More attack vectors (payment-redirect / invoice fraud) beyond credential phishing.

## Built with

Capital One Nessie · Daytona · Anthropic Claude · Gmail API · Cloudflare Tunnel · FastAPI · Python ·
vanilla JavaScript · SQLite · Playwright
