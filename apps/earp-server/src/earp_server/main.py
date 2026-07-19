"""FastAPI application factory. M1 surface: sessions CRUD, invoke, capability, audit."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from earp_server.audit.consumer import audit_handler_factory
from earp_server.capability.registry import discover, register_demo
from earp_server.config import Settings
from earp_server.gateway.auth import JWTMiddleware
from earp_server.gateway.input_guard import sanitize_body
from earp_server.infra.db import build_engine, check_db
from earp_server.infra.eventbus import EventBus
from earp_server.infra.ext import init_all
from earp_server.runtime.invoke import router as invoke_router
from earp_server.runtime.session_service import close_session, create_session, get_session
from earp_server.schemas.sessions import SessionCreateRequest, SessionResponse

APP_TITLE = "EARP Server"
APP_VERSION = "0.1.0"
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    init_all(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app.state.engine = build_engine(cfg)
        app.state.eventbus = EventBus()
        app.state.eventbus.subscribe("earp.execution.*", audit_handler_factory(app.state.engine))
        if cfg.app_env in ("dev", "test"):
            try:
                await register_demo(app.state.engine, "tenant-demo")
            except Exception:
                logger.warning("register_demo failed during lifespan startup", exc_info=True)
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(title=APP_TITLE, version=APP_VERSION, lifespan=lifespan)
    app.add_middleware(JWTMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> Any:
        ok = await check_db(app.state.engine)
        if not ok:
            return JSONResponse(status_code=503, content={"db": "fail"})
        return {"db": "ok"}

    # ── Session CRUD ──
    @app.post("/v1/sessions", response_model=SessionResponse, status_code=201, tags=["sessions"])
    async def create_session_endpoint(request_body: SessionCreateRequest, req: Request) -> SessionResponse:
        if sanitize_body(request_body.model_dump()) is None:
            raise HTTPException(status_code=400, detail="Invalid input")
        return await create_session(
            req.app.state.engine,
            req.state.tenant_id,
            req.state.user_id,
            req.state.role_id,
            metadata=request_body.metadata,
        )

    @app.get("/v1/sessions/{session_id}", response_model=SessionResponse, tags=["sessions"])
    async def get_session_endpoint(session_id: str, req: Request) -> SessionResponse:
        sess = await get_session(req.app.state.engine, session_id, req.state.tenant_id)
        if sess is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return sess

    @app.post("/v1/sessions/{session_id}/close", status_code=200, tags=["sessions"])
    async def close_session_endpoint(session_id: str, req: Request) -> dict[str, str]:
        await close_session(req.app.state.engine, session_id, req.state.tenant_id)
        return {"status": "closed"}

    app.include_router(invoke_router)

    # ── Capability Registry ──
    @app.post("/capabilities", status_code=201, tags=["capabilities"])
    async def register_capability_endpoint(req: Request) -> dict[str, str]:
        await register_demo(req.app.state.engine, req.state.tenant_id)
        return {"capability_id": "cap-demo-echo", "status": "registered"}

    @app.get("/capabilities", tags=["capabilities"])
    async def discover_capabilities_endpoint(q: str | None = None, req: Request = None) -> list[dict[str, Any]]:
        return await discover(req.app.state.engine, req.state.tenant_id, query=q)

    return app
