# HarvardHack2026

| Service | Dir | Port | Role |
| --- | --- | --- | --- |
| `proxy` | [`proxy/`](proxy/README.md) | internal (8000) | Auth proxy in front of the Nessie API; holds the API key |
| `backend` | `backend/` | 8001 | App backend (FastAPI scaffold); calls the proxy at `http://proxy:8000` |
| `frontend` | `frontend/` | 3000 | Static site served by nginx; `/api/*` is forwarded to the backend |

```bash
cp proxy/.env.example proxy/.env   # set NESSIE_API_KEY
docker compose up --build
```

Design notes: `.plans/`.
