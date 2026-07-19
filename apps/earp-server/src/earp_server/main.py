"""FastAPI application factory. M1 surface: sessions CRUD, invoke, capability, audit."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from earp_server.audit.consumer import audit_handler_factory
from earp_server.capability.registry import TokenBucketRateLimiter, discover, register_demo
from earp_server.config import Settings
from earp_server.conversation.conversation_service import (
    add_message,
    create_conversation,
    get_messages,
)
from earp_server.gateway.auth import JWTMiddleware
from earp_server.gateway.input_guard import sanitize_body
from earp_server.infra.db import build_engine, check_db
from earp_server.infra.eventbus import EventBus
from earp_server.infra.ext import init_all
from earp_server.knowledge.chunk_service import create_chunks
from earp_server.knowledge.document_service import create_document
from earp_server.knowledge.embedding_service import embed_chunks, embed_query
from earp_server.knowledge.record_manager import cleanup_old_chunks, is_unchanged
from earp_server.knowledge.search_service import search_chunks
from earp_server.planner.task_planner import SimpleTaskPlanner
from earp_server.runtime.invoke import router as invoke_router
from earp_server.runtime.session_service import close_session, create_session, get_session
from earp_server.schemas.sessions import SessionCreateRequest, SessionResponse

APP_TITLE = "EARP Server"
APP_VERSION = "0.1.0"
logger = logging.getLogger(__name__)


class PlanRequest(BaseModel):
    intent: str


class DocUpload(BaseModel):
    knowledge_base_id: str
    content: str
    title: str = ""


class SearchQuery(BaseModel):
    query: str
    top_k: int = 5


class ConvCreate(BaseModel):
    title: str = ""


class MsgAdd(BaseModel):
    role: str
    content: str


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    init_all(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app.state.engine = build_engine(cfg)
        app.state.eventbus = EventBus()
        app.state.rate_limiter = TokenBucketRateLimiter(rps=100)
        app.state.planner = SimpleTaskPlanner()
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
        return await discover(req.app.state.engine, req.state.tenant_id, role_id=req.state.role_id, query=q)

    # ── Planner ──
    @app.post("/plan", tags=["planner"])
    async def plan_endpoint(req_body: PlanRequest, req: Request) -> dict[str, Any]:
        # JWT middleware already validated tenant_id/role_id on req.state
        planner = req.app.state.planner
        try:
            steps = planner.plan(req_body.intent)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"intent": req_body.intent, "steps": [s.capability_call for s in steps]}

    @app.get("/intents", tags=["planner"])
    async def list_intents_endpoint() -> list[str]:
        from earp_server.planner.business_dictionary import RuleIntentPlanner
        return RuleIntentPlanner().list_intents()

    # ── Knowledge Base ──
    @app.post("/knowledge/documents", status_code=201, tags=["knowledge"])
    async def upload_document(req_body: DocUpload, req: Request) -> dict[str, Any]:
        engine = req.app.state.engine
        tenant_id = req.state.tenant_id
        doc = await create_document(engine, tenant_id, req_body.knowledge_base_id,
                                     req_body.content, req_body.title)
        if await is_unchanged(engine, tenant_id, doc["document_id"], doc["content_hash"]):
            return {"document_id": doc["document_id"], "status": "unchanged", "chunks": 0}
        await cleanup_old_chunks(engine, tenant_id, doc["document_id"])
        chunk_ids = await create_chunks(engine, tenant_id, doc["document_id"],
                                         req_body.content, doc["content_hash"])
        await embed_chunks(engine, tenant_id, chunk_ids)
        return {"document_id": doc["document_id"], "status": "indexed", "chunks": len(chunk_ids)}

    @app.post("/knowledge/search", tags=["knowledge"])
    async def search_knowledge(req_body: SearchQuery, req: Request) -> list[dict[str, Any]]:
        engine = req.app.state.engine
        bus = req.app.state.eventbus
        q_emb = await embed_query(req_body.query)
        return await search_chunks(engine, req.state.tenant_id, q_emb,
                                    req.state.role_id, req_body.top_k, bus)

    # ── Conversation ──
    @app.post("/conversations", status_code=201, tags=["conversations"])
    async def create_conv(req_body: ConvCreate, req: Request) -> dict[str, Any]:
        return await create_conversation(req.app.state.engine, req.state.tenant_id,
                                          req.state.user_id, req_body.title)

    @app.post("/conversations/{conv_id}/messages", status_code=201, tags=["conversations"])
    async def add_msg(conv_id: str, req_body: MsgAdd, req: Request) -> dict[str, Any]:
        return await add_message(req.app.state.engine, req.state.tenant_id,
                                  conv_id, req_body.role, req_body.content, req.state.user_id)

    @app.get("/conversations/{conv_id}/messages", tags=["conversations"])
    async def list_msgs(conv_id: str, limit: int = 50, offset: int = 0,
                         req: Request = None) -> list[dict[str, Any]]:
        return await get_messages(req.app.state.engine, req.state.tenant_id,
                                   conv_id, limit, offset)

    return app
