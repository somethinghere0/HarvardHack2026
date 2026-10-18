from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import auth_routes, db, proxy
from .config import Settings, load_settings
from .nessie import NessieClient
from .rate_limit import RateLimiter


def create_app(settings: Settings | None = None, nessie_transport=None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_db(settings.db_path)
        app.state.nessie = NessieClient(settings.nessie_base_url, settings.nessie_api_key, nessie_transport,
                                        recorder=_call_reporter(settings))
        yield
        await app.state.nessie.aclose()

    app = FastAPI(title="Nessie auth proxy", lifespan=lifespan)
    app.state.settings = settings
    app.state.limiter = RateLimiter(settings.auth_rate_limit, settings.auth_rate_window_s)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    app.include_router(auth_routes.router)
    app.include_router(proxy.router)  # catch-all, must stay last
    return app


def _call_reporter(settings: Settings):
    """Ship each upstream Nessie call to the orchestrator's API log (fire-and-forget)."""
    if not settings.orchestrator_url:
        return None
    import asyncio

    import httpx

    async def send(body: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post(f"{settings.orchestrator_url}/internal/nessie-call", json=body,
                             headers={"X-Internal-Secret": settings.internal_secret})
        except httpx.HTTPError:
            pass

    def record(method, path, status, ms, request, response):
        asyncio.get_running_loop().create_task(send({
            "method": method, "path": path, "status": status, "ms": ms,
            "request": request[:4000], "response": response[:8000]}))
    return record


def app_factory() -> FastAPI:  # uvicorn --factory app.main:app_factory
    return create_app()
