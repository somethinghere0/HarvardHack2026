from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .config import Settings, load_settings
from .daytona_detonator import DaytonaDetonator
from .detonation import HoldAllDetonator
from .gateway import Gateway
from .gmail import GmailClient
from .persona import PersonaFactory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = gmail = None
        if settings.gmail_configured:
            gmail = GmailClient(settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token)
            if settings.daytona_api_key:
                personas = PersonaFactory(settings.proxy_url, settings.proxy_username, settings.proxy_password,
                                          settings.canary_email_base)
                detonator = DaytonaDetonator(settings.daytona_api_key, personas, settings.daytona_api_url or None)
            else:
                detonator = HoldAllDetonator()
            app.state.gateway = Gateway(settings, gmail, detonator)
            task = asyncio.create_task(app.state.gateway.run_forever())
        yield
        if task:
            task.cancel()
            await gmail.aclose()

    app = FastAPI(title="HarvardHack2026 scam gateway", lifespan=lifespan)
    app.state.gateway = None

    @app.get("/health")
    def health():
        return {"status": "ok", "gateway": app.state.gateway is not None}

    @app.get("/decisions")
    def decisions():
        gw = app.state.gateway
        return gw.snapshot() if gw else []

    @app.get("/evidence/{name}")
    def evidence(name: str):
        if not re.fullmatch(r"[0-9a-f]+\.jpg", name):
            raise HTTPException(404)
        path = Path(settings.evidence_dir) / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="image/jpeg")

    return app


app = create_app()
