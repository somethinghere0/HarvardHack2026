# HarvardHack2026: scam-email gateway

Incoming email is held in quarantine until it is verified; the user's inbox only ever receives mail that passed.
Links in suspicious mail are opened in a disposable [Daytona](https://daytona.io) sandbox and fed a decoy identity
(backed by a fake customer in the Nessie bank API). If the page harvests card, bank or login details, the mail is
blocked and we record where the scammer sends the data.

```
Gmail (filter skips inbox) -> quarantine -> triage -> [links?] -> Daytona sandbox + decoy persona -> verdict
                                                                        released | blocked | held
```

| Service | Dir | Port | Role |
| --- | --- | --- | --- |
| `proxy` | [`proxy/`](proxy/README.md) | internal (8000) | Auth proxy in front of Nessie; holds the API key |
| `backend` | `backend/` | 127.0.0.1:8001 | Gmail gateway, triage, sandbox detonation, verdicts |
| `frontend` | `frontend/` | 127.0.0.1:3000 | Dashboard (`/api/*` is forwarded to the backend) |

## Setup and run

You need Docker (with Compose), Python 3.10+ (only for the one-off Gmail token step), and accounts for three
services. Do the steps in order.

### 1. Get your keys

| Key | Where | Goes in |
| --- | --- | --- |
| `NESSIE_API_KEY` | Nessie v2 API docs site ([v2-prod-api.nessieisreal.com](https://v2-prod-api.nessieisreal.com)), sign in with GitHub | `proxy/.env` |
| `DAYTONA_API_KEY` | [app.daytona.io](https://app.daytona.io) -> API Keys | `backend/.env` |
| Gmail OAuth client | step 2 below | `backend/.env` |

### 2. Connect a Gmail account

> **Use a throwaway Gmail account, not your real one.** The gateway installs a filter that diverts *all* incoming
> mail out of the inbox into `Gateway/Quarantine`, and only the gateway moves mail back.

1. In [Google Cloud Console](https://console.cloud.google.com), create a project and enable the **Gmail API**.
2. **APIs & Services -> OAuth consent screen**: choose External, and add your throwaway address under **Test users**.
3. **Credentials -> Create credentials -> OAuth client ID -> Desktop app**. Copy the client ID and secret.
4. Get the refresh token (opens a browser; sign in with the throwaway account and accept the permissions):

   ```bash
   cd backend
   pip install httpx
   python scripts/get_gmail_token.py <client_id> <client_secret>
   ```

   It prints the three `GMAIL_*` lines to paste into `backend/.env`. While the consent screen is in "Testing" mode
   Google expires the token after 7 days; just rerun the script.

### 3. Configure

```bash
cp proxy/.env.example proxy/.env       # set NESSIE_API_KEY
cp backend/.env.example backend/.env   # set GMAIL_*, DAYTONA_API_KEY, PROXY_PASSWORD (any long random string)
```

Optional in `backend/.env`: `CANARY_EMAIL_BASE=throwaway@gmail.com` (decoy emails become `throwaway+<tag>@gmail.com`,
so scammer replies reach the monitored mailbox) and `TRUSTED_DOMAINS=yourbank.com,github.com` (links to these skip
the sandbox).

### 4. Start

```bash
docker compose up --build
```

Open the dashboard at **http://localhost:3000**. Check the backend is wired up: `curl localhost:8001/health` should
return `{"status":"ok","gateway":true}`. The first scam detonation is slow (a few minutes) because Daytona builds the
browser image once; later runs reuse it.

Without the `GMAIL_*` values the gateway stays off (`"gateway":false`); without `DAYTONA_API_KEY`, any mail with
links is held rather than verified.

### 5. Use it

1. Send an email to the throwaway address. It never appears in the Gmail inbox; look under the
   `Gateway/Quarantine` label if you want to watch it arrive.
2. Within ~15 seconds the gateway triages it. Mail with no links and no red flags goes straight to the inbox.
3. Mail with links is opened in a Daytona sandbox, which fills any forms with a decoy identity. The dashboard shows
   the outcome, the evidence, the sandbox screenshot, and the URLs the page sent our decoy data to.
4. Check the Gmail labels for the result: **inbox** = released, `Gateway/Scam` = blocked,
   `Gateway/Held` = could not verify (review it manually).

To try it safely, host a fake phishing page somewhere public (the sandbox is remote and cannot reach `localhost`),
for example a static page with a "card number / CVV" form on any free static host, and email yourself the link from
another account. It should land in `Gateway/Scam` with "asks for card, cvv" in the evidence.

### Stop and clean up

```bash
docker compose down        # keep data
docker compose down -v     # also delete stored users and screenshots
```

To stop the filtering entirely, delete the filter in Gmail (**Settings -> Filters and blocked addresses**) and
move anything left in `Gateway/Quarantine` or `Gateway/Held` back to the inbox.

### Troubleshooting

- `"gateway":false` in `/health`: a `GMAIL_*` value is missing from `backend/.env`.
- Everything ends up in `Gateway/Held`: `DAYTONA_API_KEY` is missing or invalid; check `docker compose logs backend`.
- Gmail errors after about a week: the OAuth token expired (see step 2); rerun the token script.
- Mail is missing from the inbox: it is working as designed, look in `Gateway/Quarantine` or `Gateway/Held`.

## Verdicts

- **released**: no links and no red flags, or the sandbox found the links harmless.
- **blocked**: sandbox saw a page asking for card/CVV/SSN/bank details, or posting data to an exfiltration endpoint
  (Telegram bots, webhooks), or a login form with other red flags. Moved to `Gateway/Scam`, never shown.
- **held**: could not verify (page down, sandbox error, lone login form). Stays out of the inbox for review.

## Safety model

- Links open only inside a throwaway Daytona sandbox (ephemeral, auto-deleted, never reused); downloads are cancelled,
  dialogs dismissed, popups closed. Only public http(s) URLs are accepted.
- The sandbox only ever receives decoy data (Luhn-valid numbers from a reserved test range, 9xx SSNs). No user data.
- Containers run non-root, read-only, all capabilities dropped; the proxy is not published; ports bind to localhost.
- Secrets live in `.env` files (gitignored), never in the image or the frontend.

## Develop

```bash
cd backend && pip install -r requirements.txt -r requirements-dev.txt && python -m pytest
```

Design notes: `.plans/`.
