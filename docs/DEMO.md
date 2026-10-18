# Demo script — Bank of USA / Scam Tracker

A 3–4 minute live run-of-show. Two windows open: **Bank of USA** (`PUBLIC_URL/`) and **Scam Tracker**
(`PUBLIC_URL/ops.html`). Have your phone/second laptop ready to send the scam email "from a stranger."

---

## 0. Pre-demo checklist (do this before you present)

- [ ] `.env` filled: `NESSIE_API_KEY`, `ANTHROPIC_API_KEY`, `DAYTONA_API_KEY`, `GMAIL_ADDRESS` +
      `GMAIL_APP_PASSWORD`, `INTERNAL_SECRET`, and `PUBLIC_URL` (your tunnel).
- [ ] **IMAP enabled** in Gmail settings (Settings → Forwarding and POP/IMAP → Enable IMAP).
- [ ] Tunnel running: `cloudflared tunnel --url http://localhost:3000` → paste URL into `PUBLIC_URL`.
- [ ] Stack running: `./start.sh`. Confirm the startup log shows
      `Email firewall: ... watching for NEW mail` and `webhooks ... ` live.
- [ ] Open **Bank of USA** at `PUBLIC_URL/` and **Scam Tracker** at `PUBLIC_URL/ops.html`.
- [ ] On the tracker, the status strip should read **nessie / gmail / daytona / anthropic / webhooks**
      all green.
- [ ] Draft the scam email on your phone so you can send it in one tap (see §2).
- [ ] **Fallback ready:** keep the **`./simulate --drain`** button in mind — it runs the whole pipeline
      without waiting for a real email (use it if Gmail/tunnel is flaky on stage).

> Timing note: a real Daytona run spends ~2–3 min installing Chromium before the browser frames
> appear (you'll see those lines in the terminal). Start the email early, or narrate the firewall +
> dashboard while it boots.

---

## 1. The hook (20s)

> "Everyone gets phishing emails — 'unusual activity, verify your account.' Spam filters either
> delete them, so we learn nothing, or miss them, and someone gets robbed. We built a third option:
> we let the scam run — against a fake bank — and record exactly how the scammer operates."

Show **Bank of USA**: "This is a real, working bank — login, accounts, transfers — all backed by
Capital One's Nessie sandbox. Looks legit, right? That's the point."

## 2. The scam arrives (30s)

From a different email account, send to your monitored Gmail:

> **Subject:** Action required: unusual sign-in on your account
>
> We detected an unusual sign-in to your account. To avoid suspension, verify your identity now:
> `PUBLIC_URL/`  *(paste your actual Bank of USA URL here)*
> This is your final notice.

> "I'm the scammer. I just sent our user a phishing email with a link to 'verify.'"

Switch to **Scam Tracker**. Within ~10s the email appears in **`// inbound · every email vetted`**,
tagged **[SCAM] · credential_phishing · quarantined**. A safe email (send a normal one too) shows
**[SAFE] · delivered**.

> "Our firewall read every inbound email, classified this one with Claude as credential phishing,
> and quarantined it out of the inbox. But instead of just blocking it — watch what it does next."

## 3. The sandbox falls for it (90s — the centerpiece)

Click the **[SCAM]** row → the engagement opens. Point at the **live Daytona container**:

> "The system spun up a disposable sandbox — a throwaway victim machine — and dropped an AI agent
> into it. You're watching it work live."

Narrate the two panes:
- **Terminal (left):** `daytona create` → chromium boots → `opened Bank of USA sign-in` → `entered
  username + password` → `OTP read from inbox, entered ✓` → `added external payee` → `transfer … →
  mule`.
- **Browser (right):** the agent's actual screen — it lands on the sign-in page, logs in with the
  decoy credentials, and clears the one-time code.

> "The agent clicked the link, signed in as our decoy, and even handled two-factor — it read the
> one-time code from the victim's inbox and typed it in. Now the 'scammer' has access to the account."

## 4. The drain + the intel (45s)

As the transfers land, point at the indicators and timeline:

> "And here's the payoff. The scammer drains the account to a mule — and because it all runs on real
> Nessie transactions, we capture everything a bank actually needs."

Show on the detail panel:
- **Risk 100/100**, with indicators: **external payee, structuring, rapid drain, full drain**.
- The **mule account** the money went to.
- The **decoy persona** (fake identity, real Nessie account).
- The **timeline** of every step.

> "Where the money went — the mule account — and how it moved — sub-threshold structuring, drained
> within minutes. That's a fraud feed a bank could act on. No real money moved, no real person was
> ever involved."

## 5. Close (15s)

> "So: an email firewall that doesn't just block scams — it lets them play out against a decoy,
> captures the attacker's playbook, and turns every phishing attempt into threat intelligence.
> That's Bank of USA and the Scam Tracker."

---

## If something breaks on stage

- **Email doesn't show up:** check the `./start.sh` terminal for `[watcher]` lines. No new mail →
  IMAP off, or the email predates the watcher's start (send a fresh one). Worst case, click
  **`./simulate --drain`** — it runs the identical pipeline instantly.
- **Sandbox slow / Daytona hiccup:** keep narrating the firewall + dashboard; the terminal shows the
  install progress. If it stalls, use `./simulate --drain` which exercises the same login → OTP →
  drain path.
- **Status chip shows `missing`:** that integration's key isn't set — check `.env` and restart.
- **Tunnel URL changed:** quick tunnels get a new URL each run; update `PUBLIC_URL` and restart, or
  use a named tunnel for a stable address.

## One-liner for the judges

> "We let scammers rob a fake bank in a sandbox, and we keep the receipts — where the money went and
> how they moved it."
