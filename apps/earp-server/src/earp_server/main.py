"""FastAPI application factory. M0 surface: /health, /ready, sessions placeholder."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from earp_server.config import Settings
from earp_server.infra.db import build_engine, check_db
from earp_server.infra.ext import init_all
from earp_server.schemas.sessions import SessionCreateRequest, SessionResponse

APP_TITLE = "EARP Server"
APP_VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    init_all(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app.state.engine = build_engine(cfg)
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(title=APP_TITLE, version=APP_VERSION, lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> Any:
        ok = await check_db(app.state.engine)
        if not ok:
            return JSONResponse(status_code=503, content={"db": "fail"})
        return {"db": "ok"}

    @app.post("/v1/sessions", response_model=SessionResponse, status_code=201, tags=["sessions"])
    async def create_session(request: SessionCreateRequest) -> SessionResponse:
        """Placeholder: contract locked in M0 (AC-08), implementation lands in M1."""
        raise HTTPException(status_code=501, detail="Implemented in M1 (walking skeleton)")

    return app
