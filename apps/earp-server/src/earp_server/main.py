"""FastAPI application factory. M1 surface: sessions CRUD, invoke, capability, audit."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from earp_server.audit.consumer import audit_handler_factory
from earp_server.capability.registry import TokenBucketRateLimiter, discover, list_for_planning, register_demo
from earp_server.config import Settings
from earp_server.connector import LLMConnector
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
from earp_server.infra.redis_eventbus import RedisStreamsEventBus
from earp_server.knowledge.chunk_service import create_chunks
from earp_server.knowledge.document_service import create_document
from earp_server.knowledge.embedding_service import embed_chunks, embed_query
from earp_server.knowledge.record_manager import cleanup_old_chunks, is_unchanged
from earp_server.knowledge.search_service import search_chunks
from earp_server.planner.task_planner import SimpleTaskPlanner
from earp_server.runtime.invoke import router as invoke_router
from earp_server.runtime.session_service import close_session, create_session, get_session, list_sessions
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


class StreamRequest(BaseModel):
    prompt: str
    system: str = ""
    session_id: str = ""


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    init_all(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app.state.settings = cfg
        app.state.engine = build_engine(cfg)
        if cfg.app_env in ("dev", "test"):
            app.state.eventbus = EventBus()  # test/dev: in-process, no Redis dependency
        else:
            app.state.eventbus = RedisStreamsEventBus()
        app.state.rate_limiter = TokenBucketRateLimiter(rps=100)
        # Phase 2: LLM cache + structured output via Ollama
        llm_connector = LLMConnector(cfg, rate_limiter=app.state.rate_limiter)
        from earp_server.infra.llm_cache import LLMCache

        llm_cache = LLMCache(ttl=cfg.llm_cache_ttl)
        llm_connector.cache = llm_cache
        # M15: Langfuse observability tracer
        from earp_server.infra.langfuse_tracer import LangfuseTracer
        from earp_server.knowledge.embedding_service import set_tracer

        tracer = LangfuseTracer(cfg)
        llm_connector.tracer = tracer
        set_tracer(tracer)
        app.state.planner = SimpleTaskPlanner(llm=llm_connector)
        if cfg.app_env in ("dev", "test"):
            # in-process audit: subscribe handler to local EventBus
            # (prod uses independent audit worker process — see entrypoints/audit.py)
            app.state.eventbus.subscribe("earp.execution.*", audit_handler_factory(app.state.engine))
        if cfg.app_env in ("dev", "test"):
            try:
                await register_demo(app.state.engine, "tenant-demo")
            except Exception:
                logger.warning("register_demo failed, continuing")
            # test mode: also register an empty-perms version for e2e tests
            if cfg.app_env == "test":
                async with app.state.engine.connect() as conn:
                    await conn.exec_driver_sql("SET LOCAL earp.tenant_id = 'tenant-demo'")
                    await conn.exec_driver_sql(
                        "INSERT INTO business_capabilities "
                        "(capability_id, tenant_id, domain, name, type, "
                        "input_schema, output_schema, required_permissions, version) "
                        "VALUES ('cap-demo-echo', 'tenant-demo', 'demo', 'echo', 'query', "
                        "'{}', '{}', '{}', '1.0.0') "
                        "ON CONFLICT (capability_id) DO UPDATE SET required_permissions = '{}'"
                    )
                    await conn.commit()
        try:
            yield
        finally:
            tracer.flush()
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

    @app.get("/v1/sessions", tags=["sessions"])
    async def list_sessions_endpoint(
        req: Request,
        status: str | None = None,
        user_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        items, total = await list_sessions(
            req.app.state.engine,
            req.state.tenant_id,
            status=status,
            user_id=user_id,
            page=page,
            page_size=page_size,
        )
        return {"items": [i.model_dump() for i in items], "total": total, "page": page, "page_size": page_size}

    app.include_router(invoke_router)

    # ── Capability Registry ──
    @app.post("/capabilities", status_code=201, tags=["capabilities"])
    async def register_capability_endpoint(req: Request) -> dict[str, str]:
        await register_demo(req.app.state.engine, req.state.tenant_id)
        return {"capability_id": "cap-demo-echo", "status": "registered"}

    @app.get("/capabilities", tags=["capabilities"])
    async def discover_capabilities_endpoint(q: str | None = None, req: Request = None) -> list[dict[str, Any]]:
        return await discover(
            req.app.state.engine,
            req.state.tenant_id,
            role_id=req.state.role_id,
            query=q,
            settings=req.app.state.settings,
        )

    # ── Planner ──
    @app.post("/plan", tags=["planner"])
    async def plan_endpoint(req_body: PlanRequest, req: Request) -> dict[str, Any]:
        # JWT middleware already validated tenant_id/role_id on req.state
        planner = req.app.state.planner
        # Phase 3 (M11): inject real capabilities into LLM system prompt
        caps = await list_for_planning(req.app.state.engine, req.state.tenant_id)
        try:
            steps = await planner.plan(req_body.intent, capabilities=caps)
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
        doc = await create_document(engine, tenant_id, req_body.knowledge_base_id, req_body.content, req_body.title)
        if await is_unchanged(engine, tenant_id, doc["document_id"], doc["content_hash"]):
            return {"document_id": doc["document_id"], "status": "unchanged", "chunks": 0}
        await cleanup_old_chunks(engine, tenant_id, doc["document_id"])
        chunk_ids = await create_chunks(engine, tenant_id, doc["document_id"], req_body.content, doc["content_hash"])
        await embed_chunks(engine, tenant_id, chunk_ids, req.app.state.settings)
        return {"document_id": doc["document_id"], "status": "indexed", "chunks": len(chunk_ids)}

    @app.post("/knowledge/search", tags=["knowledge"])
    async def search_knowledge(req_body: SearchQuery, req: Request) -> list[dict[str, Any]]:
        engine = req.app.state.engine
        bus = req.app.state.eventbus
        q_emb = await embed_query(req_body.query, req.app.state.settings)
        return await search_chunks(
            engine,
            req.state.tenant_id,
            q_emb,
            req.state.role_id,
            req_body.top_k,
            bus,
            embedding_dim=req.app.state.settings.embedding_dim,
        )

    # ── Streaming (M8) ──
    @app.post(
        "/stream/invoke",
        tags=["streaming"],
        responses={200: {"content": {"text/event-stream": {}}, "description": "SSE token stream"}},
    )
    async def stream_invoke(req_body: StreamRequest, req: Request) -> StreamingResponse:
        """SSE streaming endpoint — streams LLM tokens via text/event-stream."""
        from earp_server.connector import LLMConnector

        llm = LLMConnector(req.app.state.settings)

        async def event_stream():
            try:
                async for token in llm.stream(req_body.prompt, system=req_body.system):
                    yield f"data: {json.dumps({'token': token.token, 'index': token.index})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── Conversation ──
    @app.post("/conversations", status_code=201, tags=["conversations"])
    async def create_conv(req_body: ConvCreate, req: Request) -> dict[str, Any]:
        return await create_conversation(req.app.state.engine, req.state.tenant_id, req.state.user_id, req_body.title)

    @app.post("/conversations/{conv_id}/messages", status_code=201, tags=["conversations"])
    async def add_msg(conv_id: str, req_body: MsgAdd, req: Request) -> dict[str, Any]:
        return await add_message(
            req.app.state.engine, req.state.tenant_id, conv_id, req_body.role, req_body.content, req.state.user_id
        )

    @app.get("/conversations/{conv_id}/messages", tags=["conversations"])
    async def list_msgs(conv_id: str, limit: int = 50, offset: int = 0, req: Request = None) -> list[dict[str, Any]]:
        return await get_messages(req.app.state.engine, req.state.tenant_id, conv_id, limit, offset)

    # ── WebSocket ──
    from earp_server.gateway.websocket_gateway import ws_endpoint

    @app.websocket("/ws/events/{session_id}")
    async def ws_events(websocket: WebSocket, session_id: str):
        await ws_endpoint(websocket, session_id)

    # ── MCP Server ──
    from earp_server.mcp.server import handle_mcp_request

    @app.post("/mcp/tools", tags=["mcp"])
    async def mcp_tools(req: Request) -> dict[str, Any]:
        body = await req.json()
        return handle_mcp_request(body.get("method", "tools/list"), body.get("params"))

    return app
