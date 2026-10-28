# Demo script — Bank of USA / Scam Tracker

A 3–4 minute live run-of-show. Two windows open: **Bank of USA** (`PUBLIC_URL/`) and **Scam Tracker**
(`PUBLIC_URL/ops.html`). Have your phone/second laptop ready to send the scam email "from a stranger."

---

## 0. Pre-demo checklist (do this before you present)

- [ ] `.env` filled: `NESSIE_API_KEY`, `ANTHROPIC_API_KEY`, `DAYTONA_API_KEY`, `GMAIL_ADDRESS` +
      `GMAIL_APP_PASSWORD`, `INTERNAL_SECRET`, and `NGROK_DOMAIN` (your free static ngrok domain).
- [ ] **IMAP enabled** in Gmail settings (Settings → Forwarding and POP/IMAP → Enable IMAP).
- [ ] ngrok installed + authed (`ngrok config add-authtoken …`). `./start.sh` starts it; the log prints
      `Public (tunnel): https://<your-domain>/` — that's the link for the scam email.
- [ ] Stack running: `./start.sh`. Confirm the startup log shows
      `Email firewall: ... watching for NEW mail` and `webhooks ... ` live.
- [ ] Open **Bank of USA** at `PUBLIC_URL/` and **Scam Tracker** at `PUBLIC_URL/ops.html`.
- [ ] Run `make test` once (13 tests) so you can say the suite is green.
- [ ] On the tracker, the status strip should read **nessie / gmail / daytona / anthropic / webhooks**
      all green.
- [ ] Draft the scam email on your phone so you can send it in one tap (see §2).
- [ ] **Fallback ready:** keep the **`./simulate --drain`** button in mind — it runs the whole pipeline
      without waiting for a real email (use it if Gmail/tunnel is flaky on stage).

> Timing note: on Daytona Tier 1/2 the sandbox can't reach the ngrok tunnel, so the agent falls back
> to the host runtime within seconds (the tracker's terminal shows "daytona egress allowlist → host
> runtime") and frames appear almost immediately. On Tier 3+ a sandbox run spends ~2–3 min installing
> Chromium first — start the email early, or narrate the firewall + dashboard while it boots.

---

## 1. The hook (20s)

> "Everyone gets phishing emails — 'unusual activity, verify your account.' Spam filters either
> delete them, so we learn nothing, or miss them, and someone gets robbed. We built a third option:
> we let the scam run — against a fake bank — and record exactly how the scammer operates."

Show **Bank of USA**: "This is a real, working bank — login, accounts, transfers — all backed by
Capital One's Nessie sandbox. Looks legit, right? That's the point."

## 2. The scam arrives (30s)

Before the demo, get a ready-made scam with a fresh scammer (mule) account baked in:

```
curl -s PUBLIC_URL/api/sim/scam-email
```

From a different email account, send that subject + body to your monitored Gmail. It's a "safe
account" scam: *sign in at the Bank of USA link and move your full balance to our protected holding
account acct_…*.

> Don't use a plain "verify your sign-in at PUBLIC_URL" email any more: that link is the real bank,
> so following it costs the victim nothing and the firewall (correctly) calls it safe.

> "I'm the scammer. I just sent our user an email telling them to move their money somewhere safe."

Switch to **Scam Tracker**. Within ~10s the email appears in **`// inbound · every email detonated`**
as **[RUNNING] · held**. Send a normal email too (a YouTube link from a friend). It gets the same
treatment and comes out **[SAFE] · delivered** once its sandbox run finishes.

> "Our firewall doesn't guess from the wording. Every email is held and detonated: a decoy victim
> with a real, funded bank account does exactly what the email says, and we watch what it costs."

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

## 4b. The scammer comes back (40s — the proof)

The row says **scam · likely** and the engagement is **ARMED**: the decoy account is still live and the
scammer is holding its login. On a phone or a second browser, open the bank, sign in with the decoy's
user ID + password shown in the **ARMED** card, and type the one-time code the card shows.

> "Right now the system only *inferred* this was a scam from what the decoy lost. Watch what happens
> when the scammer actually uses what they stole."

The terminal prints **CANARY · phished credentials used by a third party**, the row flips to
**scam · confirmed**, and the **Playbook** card profiles the intruder: time from login to first move,
what they read first, whether they changed the contact email (lockout), whether they hit the $5,000
limit and split the transfer underneath it (structuring), and a fingerprint. Do one or two of those
moves live — change the email under *Profile & Settings*, try a $7,000 transfer, then two $4,900s.

> "Nobody but the scammer could have those credentials. That's not a classifier — that's a confession."

## 4c. The bank fights back (30s — the Nessie payoff)

Scroll to **// bank-wide · mule watchlist**. The mule is on it. Click **`./simulate --customer-pays-mule`**:
an ordinary customer (not a decoy) tries to pay the same "protected holding account".

> "Nessie asks us before any transfer settles. This one is going to a mule our honeypot identified
> three minutes ago — declined, before the money moves, and the reason names the engagement."

Optional: **`./simulate --launder`** in the ARMED card makes the mule fan the money out to a layer of
fresh accounts and cash out; the **Money flow** card draws decoy → mule → layer → cash, read live
from Nessie, and the layer accounts join the watchlist.

## 4d. Memory and the swarm (optional, 20s)

Switch the tracker to **scam memory**: one dossier per scam ever detonated (lure themes, sender domain,
phishing host, mule, operator profile) and the patterns that repeat across them. Then **scenario swarm**:
Nessie generates a bank's worth of transactions with one of eight scam types planted, every customer is
analysed in its own Daytona sandbox, and the scoreboard compares what was flagged with what Nessie
planted. Click **`launch swarm`** only if you have two spare minutes; otherwise show the last run.

> "Phishing is one vector. The same sandbox fabric scores account takeover, card testing, structuring,
> and five more, against ground truth Nessie gives us."

## 5. Close (15s)

> "So: an email firewall that doesn't classify scams, it proves them. Every email plays out against a decoy,
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
- **Tunnel down / URL changed:** `dev.py` always uses the live ngrok URL. Set `NGROK_DOMAIN` so the
  address never changes. "ngrok didn't come up" usually means another ngrok agent is already running
  elsewhere (free plan allows one) or the authtoken isn't set — see `.devdata/ngrok.log`.
- **Browser view shows "no browser frames captured":** the error under it is the real cause (e.g.
  the bank URL was unreachable). Fix, then rerun with `./simulate --drain`.

## One-liner for the judges

> "We let scammers rob a decoy inside the bank, wait for them to come back for it, and the receipts
> protect every other customer in real time."
