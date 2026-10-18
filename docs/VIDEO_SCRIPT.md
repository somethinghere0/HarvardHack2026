# Video script — Bank of USA / Scam Tracker (2:30–3:00)

**Layout:** vertical phone video on the LEFT (you, acting), screen recording of the demo on the RIGHT.
Spoken lines are in quotes. Everything else is a stage/screen cue.
Target pace: ~150 words/min. Spoken total ≈ 420 words.

---

## 0:00–0:25 — THE HOOK (the problem, acted out)

**Phone:** you on the couch, scrolling your inbox, half-paying attention.
**Screen (right):** your Gmail with the scam email open. Subject like *"Unusual activity — move your funds to a protected account."*

> "Yo, Bank of USA says there's unusual activity on my account… okay, 'sign in here and move your balance to a safe holding account.' Sure, whatever."

**Screen:** tap the link → the bank sign-in page → type username + password → enter the one-time code from your texts → start a transfer to `acct_…` "protected holding account." Hit send.

**Phone:** hard cut to you looking up, deadpan.

> "I just gave a stranger my login, my two-factor code, and my savings. That took forty seconds. Spam filters either delete emails like this, so nobody learns anything, or they miss one, and this happens to a real person."

---

## 0:25–0:45 — THE IDEA

**Screen:** Scam Tracker dashboard, `ops.html`, status strip green: nessie / gmail / daytona / anthropic / webhooks.

> "So we built an email firewall that doesn't *guess* if an email is a scam. It *lets the scam happen*, to a fake victim, and records everything.
> Meet Bank of USA, a fully working bank on Capital One's Nessie sandbox, and the Scam Tracker that sits in front of your inbox."

---

## 0:45–1:15 — EVERY EMAIL GETS DETONATED

**Screen:** the `// inbound · every email detonated` list. Send the scam email from your phone (or hit `./simulate --drain`). The row appears as `[RUNNING] · held`. A normal email from a friend shows `[SAFE] · delivered`.

> "Every inbound email is held. Claude reads what it's asking you to do: click a link, sign in, send money, hand over a code.
> Then the system builds a decoy victim: a made-up identity with a real, funded Nessie bank account, and drops an AI agent into a disposable Daytona sandbox to go do exactly what the email says."

---

## 1:15–1:45 — WATCH THE AGENT FALL FOR IT (centerpiece)

**Screen:** click the row → engagement view. Left pane: live terminal. Right pane: the agent's actual browser.

> "You're watching it live. The agent opens the link, logs in as the decoy, reads the one-time code out of the victim's inbox, types it in, adds the scammer's payee, and sends the money.
> A normal email costs the decoy nothing, so it's delivered. This one drained the account, so it's quarantined. The verdict comes from what actually happened, not from how the email reads."

---

## 1:45–2:15 — THE INTEL (what a bank actually gets)

**Screen:** detail panel. Point at Risk 100/100, indicators (external payee, rapid drain, structuring, full drain), the mule account, the timeline.

> "And here's the payoff. Because it ran on real bank transactions, we capture the two things a bank can act on: *where* the money went, the mule account, and *how* it moved."

**Screen:** the ARMED card. On your phone, sign in to the bank with the decoy's credentials. Terminal prints `CANARY · phished credentials used by a third party`; the row flips `scam · likely` → `scam · confirmed`. The Playbook card fills in.

> "The decoy stays armed. When the scammer actually comes back and uses the stolen login, that's not a classifier anymore, that's a confession. We profile them: how fast they move, what they read first, whether they lock the victim out, whether they split transfers under the $5,000 limit."

---

## 2:15–2:40 — THE BANK FIGHTS BACK

**Screen:** scroll to `// bank-wide · mule watchlist`. Click `./simulate --customer-pays-mule`. The transfer is declined with a reason naming the engagement. Optional: `./simulate --launder` → Money flow draws decoy → mule → layer → cash.

> "Every mule we find goes on a watchlist. Nessie asks us before any transfer settles, so when a real customer tries to pay that same account three minutes later, it's declined before the money moves.
> Scam memory links engagements by the same mule, sender, or playbook fingerprint, so one honeypot turns every phishing attempt into threat intel for the whole bank."

---

## 2:40–2:55 — CLOSE

**Phone:** back to you.

> "We let scammers rob a decoy, wait for them to come back for it, and the receipts protect everyone else in real time.
> That's Bank of USA and the Scam Tracker."

**Screen:** end card: logo + stack (Nessie · Claude · Daytona · Gmail · ngrok) + repo URL.

---

## Recording tips

- Record the screen side first, then act the phone side to match its timing. The sandbox run is the one part you can't fake, so capture it once cleanly and cut around it.
- Pre-bake the scam email with `curl -s PUBLIC_URL/api/sim/scam-email` so the mule account already exists.
- Keep the hook under 25s. The deadpan cut at 0:20 is the whole joke; don't over-explain it.
- If you need to trim to 2:30, drop the `--launder` beat and shorten the playbook line to "and we profile how they operate."
