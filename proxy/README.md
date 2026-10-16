# HarvardHack2026: Nessie auth proxy

A Dockerized FastAPI proxy in front of the [Nessie v2 API](https://v2-prod-api.nessieisreal.com). Users sign up and
log in with a username and password; the proxy keeps the Nessie API key server-side and forwards authenticated
requests to Nessie at the same paths.

## Run

```bash
cp .env.example .env        # set NESSIE_API_KEY (from the repo root, see top-level README)
docker compose up --build   # http://localhost:8000
```

Terminate TLS in front of the container; don't expose it over plain HTTP outside localhost.

## Use

```bash
curl -X POST localhost:8000/auth/signup -H 'Content-Type: application/json' -d '{
  "username":"alice","password":"correct horse","first_name":"Alice","last_name":"Ng",
  "address":{"street_number":"1","street_name":"Main St","city":"McLean","state":"VA","zip":"22101"}}'
# -> {"token":"...","expires_at":"...","customer_id":"..."}

curl -X POST localhost:8000/auth/login -H 'Content-Type: application/json' -d '{"username":"alice","password":"correct horse"}'
curl localhost:8000/accounts -H "Authorization: Bearer $TOKEN"     # any Nessie path works
```

| Route | Auth | Purpose |
| --- | --- | --- |
| `POST /auth/signup` | none | Create user and Nessie customer, return session token |
| `POST /auth/login` | none | Return session token |
| `POST /auth/logout` | session | Revoke the token |
| `GET /auth/me` | session | Current username and Nessie customer id |
| `GET /health` | none | Liveness |
| everything else | session | Forwarded to Nessie with the server-held key |

Known limits: access is gate-only (any logged-in user can call any Nessie route, they share one tenant and its rate
limit), and the login limiter is in-memory per container.

## Develop

```bash
pip install -r requirements.txt pytest && python -m pytest
```

Design and diagrams: `../.plans/2026-10-16-nessie-auth-proxy/PLAN.md`.
