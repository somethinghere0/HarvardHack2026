# Decoy — Devpost submission

Paste-ready text for the Devpost story form.

**Tagline:** An email firewall that doesn't classify scams. It proves them.

---

## Inspiration

Everyone has gotten the email: *"Unusual activity on your account. Sign in now and move your balance to a protected holding account."* Today a bank has two bad options. The spam filter deletes it, and the bank learns nothing about who sent it, where the money would have gone, or how the crew operates. Or the filter misses it, and a real customer loses their savings in forty seconds.

Filters guess from wording. We wanted a system that doesn't guess. What if every suspicious email got exactly what it asked for, from a victim who doesn't exist, with money that isn't real, while a fraud team watches? The scammer gets a decoy. The bank gets the two things it can actually act on: where the money went and how it moved. And if the scammer comes back to use the login they stole, that's no longer a classification. That's a confession.

## What it does

Decoy sits in front of a bank's inbox and **detonates every email instead of classifying it.**

1. **Hold and brief.** A watcher pulls new mail from Gmail. Claude extracts what the email asks the reader to do: links to open, places to sign in, money to send, codes to hand over. That briefs the victim. It is not the verdict.
2. **Build a victim on the spot.** A Claude-invented identity, a real login created through our bank's signup path, and a Capital One Nessie customer with checking, savings, and a credit card, seeded with payroll history so it doesn't look brand new.
3. **Fall for it, on purpose.** Inside a disposable Daytona sandbox, a Playwright + Claude browser agent plays the recipient and does exactly what the email says: opens the link, signs in, reads the one-time code out of the decoy's inbox, adds the payee, sends the money. You watch it live: a streaming terminal on the left, the agent's actual browser frames on the right.
4. **Judge by what complying cost.** Money left the decoy, or its credentials landed outside the bank: **scam**, quarantined. Full compliance and nothing lost: **safe**, delivered. A note from a friend goes through the same chamber and comes out clean.
5. **Stay armed.** The decoy's phished login keeps working. Our agent tags its own requests; any sign-in without that tag is a third party holding the stolen password. That canary upgrades the verdict from *scam · likely* to *scam · confirmed*, with proof from outside the sandbox.
6. **Profile the intruder.** Every move inside the decoy is attributed to a session and an actor. The account is built as a set of tripwires: savings holds more than checking, there's a $5,000 per-transfer limit, and the contact email for one-time codes is editable. A playbook engine turns the timeline into the account-takeover kill chain (access → recon → lockout → drain → cash-out) with timing, declines, structuring, an op-sequence fingerprint, and an operator profile. An indicator engine scores it 0–100.
7. **Fight back bank-wide.** Every mule account a scam drained to goes on a watchlist. We register a Nessie decision hook, so Nessie asks us before any transfer settles. An ordinary customer paying a known mule is **declined before the money moves**, citing the engagement that found it. Decoy also links engagements into crews, draws the money flow past the mule live from Nessie, and keeps a searchable memory of every lure, domain, host, and mule it has seen.
8. **Scenario swarm.** Nessie's traffic simulator plants one of eight fraud types across a bank's worth of transactions. Each customer becomes a case in its own Daytona sandbox running a rules detector that escalates only borderline transactions to Claude, scored against Nessie's planted count with a clean control run.

No real money moves and no real person is involved. The bank is original branding, Gmail actions are label-only, and every session is scoped to its own decoy customer.

## How we built it

- **Capital One Nessie v2** as the data and enforcement layer: customers, accounts, deposits and transfers, the events feed, webhooks, the traffic simulator, and the decision hook that lets us decline a pending transfer.
- **Bank of USA**, a working retail bank over Nessie (vanilla JS, no build step), so the phishing link lands on something real.
- **Auth proxy (FastAPI).** Holds the Nessie key server-side and adds username/password login, an emailed one-time code, per-customer scoping, the transfer limit, and session telemetry on every request. That attribution is what makes the canary and the playbook possible.
- **Orchestrator (FastAPI + SQLite).** Email intake, decoy lifecycle, the agent runner, Nessie event ingest, the outcome judge, indicators, playbook, intel, scam memory, and the swarm. Detonations resume across restarts.
- **Claude (Anthropic).** Extracts the asks, invents the victims, drives the browser agent, and handles borderline escalations in the swarm. Credentials never enter the prompt: Claude types placeholders and the agent substitutes real values.
- **Daytona.** A fresh sandbox per engagement and per swarm case. The runner probes the sandbox's route to our tunnel and falls back to host Chromium when the tier's egress allowlist blocks it.
- **Gmail over IMAP/SMTP** for inbound mail and OTP delivery, **ngrok** for the public URL, webhooks, and decision hook, and a dark terminal-styled **Scam Tracker** UI with a live sandbox viewer.

## Challenges we ran into

- **Making the agent gullible.** A capable model refuses to type a password into a phishing page. We reframed it as a victim simulator inside a fraud team's detonation chamber, made clear the system decides the verdict, not the agent, and kept real secrets out of the prompt. It now follows the email all the way to the drain.
- **Judging too early.** Nessie settles asynchronously. The proxy sees an accepted transfer before the ledger reports it, and judging in that gap called a drained account safe. The judge now waits for the ledger to confirm outflows, and relabels mail if a late transfer flips the verdict.
- **Daytona's egress allowlist.** Lower tiers can't reach ngrok. We built a probe-and-fall-back runtime and made the tracker say which one is running.
- **A watchlist that actually blocks.** Decision hooks are one-per-kind, so stale hooks from crashed runs had to be cleaned up on boot, and the hosted API's settlement sweep can lag, so the feed decides hits out of band.
- **Four people, one dev stack, hackathon pace.** Targeted edits, restart discipline, and checking for in-flight detonations before restarting anything.

## Accomplishments that we're proud of

- A genuinely end-to-end attack and defense on live APIs: email → extraction → decoy → sandboxed agent → real Nessie drain → verdict → canary → playbook → watchlist → a declined transfer, all watchable in real time.
- The canary. Proof an email is a scam from the scammer's own hand, not a model's opinion.
- A behavioral verdict with no allowlists and no heuristics on wording. Safe mail costs nothing and is delivered.
- Bank-wide protection from a single honeypot: one phishing email becomes a blocked transfer for every other customer.
- A demo that survives the stage: resumable detonations, runtime fallback, one-click simulations.

## What we learned

- **Outcome beats intent.** "What did complying cost?" is a more honest signal than "does this read like a scam?", and it generalizes to lures a classifier has never seen.
- **Attribution is the whole game.** Tagging every bank operation with a session and actor was a tiny proxy change that unlocked the canary, the playbook, and the crew graph.
- **Design the decoy as an instrument.** Three products, a transfer limit, and editable contact details turn a drain into answered questions about how the operator works.
- **Sandboxes make "let the attack run" safe to say out loud.** Every victim is disposable, every secret is fake, every session is scoped.

## What's next for Decoy

- A shared feed of fresh mule accounts and playbook fingerprints that other banks or a consortium could screen against, the way our decision hook screens Bank of USA.
- More lure types: invoice and payment-redirect fraud, plus SMS and voice follow-ups to the decoy's phone.
- Prebuilt Daytona snapshots with Chromium baked in for near-instant detonations, and higher-tier egress so the agent always runs in the sandbox.
- Longer-lived decoys that keep replying to the scammer to pull out more of the crew's infrastructure.
