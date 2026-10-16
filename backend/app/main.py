import os

from fastapi import FastAPI

PROXY_URL = os.environ.get("PROXY_URL", "http://proxy:8000")

app = FastAPI(title="HarvardHack2026 backend")


@app.get("/health")
def health():
    return {"status": "ok"}
