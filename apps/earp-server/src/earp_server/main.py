"""FastAPI application factory. M1 surface: sessions CRUD, invoke, capability, audit."""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from earp_server.admin.model_routes import router as model_routes_router
from earp_server.admin.roles_routes import router as roles_router
from earp_server.audit.consumer import audit_handler_factory
from earp_server.capability.registry import TokenBucketRateLimiter, discover, list_for_planning, seed_demo_tenant
from earp_server.config import Settings
from earp_server.connector import LLMConnector
from earp_server.conversation.conversation_service import (
    add_message,
    create_conversation,
    get_messages,
    list_conversations,
)
from earp_server.conversation.chat_app_service import (
    create_chat_app,
    delete_chat_app,
    get_chat_app,
    list_chat_apps,
    publish_chat_app,
    update_chat_app,
)
from earp_server.conversation.chat_service import ChatError, chat_sse, flow_chat
from earp_server.gateway.auth import JWTMiddleware, create_token
from earp_server.gateway.input_guard import sanitize_body
from earp_server.infra.db import build_engine, check_db
from earp_server.infra.eventbus import EventBus
from earp_server.infra.ext import init_all
from earp_server.infra.redis_eventbus import RedisStreamsEventBus
from earp_server.infra.task_queue import ProcrastinateTaskQueue
from earp_server.knowledge.admin_service import (
    DataDomainInUseError,
    create_data_domain,
    create_kb,
    delete_data_domain,
    delete_document,
    delete_kb,
    get_document_detail,
    list_data_domains,
    list_documents,
    list_kbs,
    reindex_document,
    reindex_kb,
    save_document_process_rule,
    update_data_domain,
    update_document_classification,
    update_document_status,
    update_kb,
    update_kb_retrieval,
)
from earp_server.knowledge.chunk_service import build_preview, create_chunks, suggest_separators
from earp_server.knowledge.document_service import create_document, find_duplicate, update_document_metadata
from earp_server.knowledge.embedding_service import embed_chunks, embed_query
from earp_server.knowledge.file_parser import FileParseError, extract_text
from earp_server.knowledge.routing import build_routing_index, route_debug, route_query
from earp_server.knowledge.search_service import search_chunks
from earp_server.ontology.eval_routes import router as eval_router
from earp_server.ontology.routes import router as ontology_router
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
    data_classification: str = "internal"
    metadata: dict | None = None  # manual doc metadata (validated vs KB schema)


class SearchQuery(BaseModel):
    query: str
    top_k: int = 5
    knowledge_base_ids: list[str] | None = None
    data_domain_ids: list[str] | None = None
    threshold: float | None = None  # minimum cosine similarity (0..1)
    mode: str = "vector"  # vector | hybrid
    metadata_filters: dict | None = None  # JSONB containment on documents.metadata


class MetadataUpdate(BaseModel):
    metadata: dict


class RoutingDebugRequest(BaseModel):
    query: str
    top_n: int = 3  # candidate DDs
    top_k: int = 3  # candidate KBs


class RoutingRebuildRequest(BaseModel):
    data_domain_ids: list[str] | None = None  # None = all domains
    knowledge_base_ids: list[str] | None = None


class RoutingSuggestRequest(BaseModel):
    data_domain_id: str


async def _llm_suggest(engine, tenant_id: str, settings: Settings, prompt: str) -> str:
    """AI-assist draft via the DB-configured default LLM (PRD-2026-031, env fallback).
    Returns the parsed JSON "description" field. 2026-08-09 C 决策: DB 模型优先。

    Phase B 决策 D4 方案 A：薄封装——load_runtime_models 解析 model_override →
    LLMConnector.json_complete → 抽 description 字段；签名/响应不变（调用点零改动）。
    """
    llm_cfg: dict = {}
    try:
        from earp_server.admin import model_service as _ms

        llm_cfg = (await _ms.load_runtime_models(engine, tenant_id)).get("llm") or {}
    except Exception:
        logger.warning("_llm_suggest: load_runtime_models failed — env defaults", exc_info=True)
    from earp_server.connector import LLMConnector

    conn = LLMConnector(settings, model_override=llm_cfg or None)
    data = await conn.json_complete(
        "你是企业知识库的领域描述撰写助手。根据输入输出简洁准确的检索描述。",
        prompt,
    )
    if data is None:
        provider = llm_cfg.get("provider") or "ollama"
        model_name = llm_cfg.get("model_name") or settings.ollama_chat_model
        raise HTTPException(status_code=502, detail=f"LLM 生成失败({provider}/{model_name})")
    return str(data.get("description", ""))


class KBCreate(BaseModel):
    name: str
    data_domain_id: str | None = None
    description: str | None = None
    retrieval_model: dict | None = None  # {segmentation:{separator,max_tokens,chunk_overlap},
    #  mode, top_k, score_threshold, model}
    indexing_technique: str = "high_quality"  # high_quality | economy
    metadata_schema: list[dict] | None = None  # [{"key":"department","type":"string",...}]
    summary_text: str | None = None  # KB 检索摘要（空=自动聚合，非空=人工覆盖）


class DocClassUpdate(BaseModel):
    data_classification: str


class DocStatusUpdate(BaseModel):
    status: str  # active | disabled


class DocProcessRule(BaseModel):
    rules: dict  # {segmentation: {...}, pre_processing_rules: [...]}


class ChunkPreviewRequest(BaseModel):
    content: str
    max_tokens: int = 1000
    chunk_overlap: int = 200
    separator: str = "\n\n"  # legacy single separator
    separators: list[str] | None = None  # priority-ordered list (takes precedence)
    remove_extra_spaces: bool = True


class DocPreviewRequest(BaseModel):
    """Doc preview: content is read server-side from the document row."""

    max_tokens: int = 1000
    chunk_overlap: int = 200
    separator: str = "\n\n"
    separators: list[str] | None = None
    remove_extra_spaces: bool = True


class KBRetrievalUpdate(BaseModel):
    retrieval_model: dict | None = None
    indexing_technique: str | None = None


class KBUpdate(BaseModel):
    """KB basic attributes edit."""

    name: str | None = None
    data_domain_id: str | None = None
    description: str | None = None
    indexing_technique: str | None = None
    metadata_schema: list[dict] | None = None
    summary_text: str | None = None


class DataDomainUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    data_classification: str | None = None
    owner: str | None = None
    routing_description: str | None = None  # retrieval description (empty = auto)


class DataDomainCreate(BaseModel):
    data_domain_id: str
    name: str
    data_classification: str = "internal"
    description: str | None = None
    owner: str | None = None


class ConvCreate(BaseModel):
    title: str = ""


class MsgAdd(BaseModel):
    role: str
    content: str


class ChatAppCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    system_prompt: str | None = None  # None → DB 默认模板
    orchestration: str = "auto"  # Chatflow F1: auto | flow（默认 auto，前端零改动）
    flow_schema: dict[str, Any] | None = None  # flow 模式必填，图校验（F0 白名单扩展）


class ChatAppUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    kb_scope: list[str] | None = None
    retrieval: dict[str, Any] | None = None
    generation: dict[str, Any] | None = None
    model_config_id: str | None = None
    context_turns: int | None = None
    orchestration: str | None = None
    flow_schema: dict[str, Any] | None = None


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    conversation_id: str | None = None


class LoginRequest(BaseModel):
    tenant_id: str
    user_id: str
    role_id: str


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
        # T1: 任务队列 — API 进程只 enqueue（worker 进程消费 eval.run 等）。
        # 连接失败不阻塞启动（/ready 语义：DB 不可达时 503，AC-01）；
        # enqueue 时连接错误会在请求层暴露。
        queue = ProcrastinateTaskQueue(cfg)
        try:
            await queue.open()
            await queue.assert_schema()
        except Exception:  # noqa: BLE001 — DB 未就绪/迁移未跑时应用仍可起
            logger.warning("task queue init failed — enqueue will fail until DB/schema ready", exc_info=True)
        app.state.queue = queue
        if cfg.app_env in ("dev", "test"):
            app.state.eventbus = EventBus()  # test/dev: in-process, no Redis dependency
        else:
            app.state.eventbus = RedisStreamsEventBus()
        app.state.rate_limiter = TokenBucketRateLimiter(rps=100)
        # P3: reranker init (default disabled — graceful RRF-only when unavailable)
        from earp_server.infra.ext.ext_reranker import init_reranker_provider as _init_rrk

        _init_rrk(
            provider=getattr(cfg, "rerank_provider", "none"),
            ollama_base_url=getattr(cfg, "ollama_base_url", "http://localhost:11434"),
            ollama_model=getattr(cfg, "ollama_rerank_model", "bge-reranker-v2-m3"),
            openai_api_key=getattr(cfg, "openai_api_key", ""),
        )
        # Phase 2: LLM cache + structured output via Ollama
        llm_connector = LLMConnector(cfg, rate_limiter=app.state.rate_limiter)
        # PRD-2026-031: DB-configured models take priority (env fallback inside connector)
        try:
            from earp_server.admin import model_service as _ms
            from earp_server.infra.ext.ext_embedding import init_embedding_provider as _reinit_emb

            runtime_models = await _ms.load_runtime_models(app.state.engine, "tenant-demo")
            llm_config = runtime_models.get("llm")
            if llm_config:
                llm_connector = LLMConnector(cfg, rate_limiter=app.state.rate_limiter, model_override=llm_config)
            emb = runtime_models.get("embedding")
            if emb:
                if emb["provider"] == "ollama":
                    _reinit_emb(provider="ollama", ollama_base_url=emb.get("base_url"), ollama_model=emb["model_name"])
                elif emb["provider"] == "openai":
                    _reinit_emb(
                        provider="openai",
                        openai_api_key=emb.get("api_key"),
                        openai_model=emb["model_name"],
                        openai_base_url=emb.get("base_url") or "https://api.openai.com/v1",
                    )
            rr = runtime_models.get("rerank")
            if rr:
                _init_rrk(
                    provider=rr["provider"],
                    ollama_base_url=rr.get("base_url"),
                    ollama_model=rr["model_name"],
                )
        except Exception:
            logger.warning("load_runtime_models failed — using env defaults", exc_info=True)
        from earp_server.infra.llm_cache import LLMCache

        llm_cache = LLMCache(ttl=cfg.llm_cache_ttl)
        llm_connector.cache = llm_cache
        # M15: Langfuse observability tracer
        from earp_server.infra.langfuse_tracer import LangfuseTracer

        tracer = LangfuseTracer(cfg)
        llm_connector.tracer = tracer
        app.state.planner = SimpleTaskPlanner(llm=llm_connector)
        app.state.llm = llm_connector  # P1 chat 链路直接使用（含 DB model_configs 解析）
        if cfg.app_env in ("dev", "test"):
            # in-process audit: subscribe handler to local EventBus
            # (prod uses independent audit worker process — see entrypoints/audit.py)
            app.state.eventbus.subscribe("earp.execution.*", audit_handler_factory(app.state.engine))
            app.state.eventbus.subscribe("earp.chat_app.*", audit_handler_factory(app.state.engine))
            # Chatflow F3: capability 节点审计（capability.call 层事件 → audit_logs）
            app.state.eventbus.subscribe("earp.capability.*", audit_handler_factory(app.state.engine))
        if cfg.app_env in ("dev", "test"):
            try:
                # Seed demo tenant baseline: tenant/user/role/data-domains/capability.
                # Fixes dev blockers: invoke 403 (empty roles), KB create 500 (missing
                # data domains FK), conversation create 500 (empty users).
                await seed_demo_tenant(app.state.engine, "tenant-demo")
            except Exception:
                logger.warning("seed_demo_tenant failed, continuing")
        try:
            yield
        finally:
            tracer.flush()
            await queue.close()
            await app.state.engine.dispose()

    app = FastAPI(title=APP_TITLE, version=APP_VERSION, lifespan=lifespan)
    # CORS must be added AFTER JWTMiddleware so it wraps it (Starlette LIFO) and
    # handles preflight OPTIONS before JWT auth — otherwise cross-origin admin
    # dashboard calls fail with "Failed to fetch" (no Access-Control-Allow-* headers).
    # Dev/test: allow all origins. Prod: restrict via env (EARP_CORS_ORIGINS).
    app.add_middleware(JWTMiddleware)
    _cors_origins = [o.strip() for o in cfg.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins if _cors_origins else ["*"],
        allow_credentials=bool(_cors_origins),  # wildcard + credentials is illegal per CORS spec
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Admin dashboard static hosting (同源，apiBase='/' 直达 API)
    _admin_dir = pathlib.Path(__file__).resolve().parents[3] / "earp-admin"
    if _admin_dir.exists():
        app.mount("/admin", StaticFiles(directory=str(_admin_dir), html=True), name="admin")

    @app.middleware("http")
    async def no_cache_admin_html(request: Request, call_next):
        """Don't cache ANY admin static asset (HTML/CSS/JS) — dev pages change
        frequently; stale caches caused users to see old layouts (KB list issues).
        Dev only; prod should serve assets with proper caching."""
        response = await call_next(request)
        if request.url.path.startswith("/admin"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # ── Dev/test login: issues a JWT for the admin dashboard ──
    @app.post("/auth/login", tags=["auth"])
    async def auth_login(req_body: LoginRequest, req: Request) -> dict[str, Any]:
        """Dev/test convenience: tenant/user/role -> JWT. Disabled in prod.

        Validates the identities exist (RLS-scoped for user/role) so the issued
        token is guaranteed usable — a token with an unknown role_id would fail
        PolicyLayer with a confusing 403 later.
        """
        from sqlalchemy import text

        cfg = req.app.state.settings
        if cfg.app_env == "prod":
            raise HTTPException(status_code=404, detail="dev login endpoint disabled in prod")
        engine = req.app.state.engine

        async with engine.connect() as conn:
            t = await conn.execute(text("SELECT 1 FROM tenants WHERE tenant_id = :tid"), {"tid": req_body.tenant_id})
            if t.fetchone() is None:
                raise HTTPException(status_code=404, detail=f"Tenant not found: {req_body.tenant_id}")
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{req_body.tenant_id}'"))
            r = await conn.execute(text("SELECT 1 FROM roles WHERE role_id = :rid"), {"rid": req_body.role_id})
            if r.fetchone() is None:
                raise HTTPException(status_code=404, detail=f"Role not found: {req_body.role_id}")
            u = await conn.execute(text("SELECT 1 FROM users WHERE user_id = :uid"), {"uid": req_body.user_id})
            if u.fetchone() is None:
                raise HTTPException(status_code=404, detail=f"User not found: {req_body.user_id}")

        token = create_token(sub=req_body.user_id, tenant_id=req_body.tenant_id, role_id=req_body.role_id)
        return {
            "token": token,
            "token_type": "bearer",
            "expires_in": 7 * 24 * 3600,
            "tenant_id": req_body.tenant_id,
            "user_id": req_body.user_id,
            "role_id": req_body.role_id,
        }

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
    app.include_router(ontology_router)
    app.include_router(eval_router)
    app.include_router(model_routes_router)
    app.include_router(roles_router)

    # ── Capability Registry ──
    @app.post("/capabilities", status_code=201, tags=["capabilities"])
    async def register_capability_endpoint(req: Request) -> dict[str, str]:
        await seed_demo_tenant(req.app.state.engine, req.state.tenant_id)
        return {"capability_id": "cap-demo-echo", "status": "registered"}

    @app.get("/capabilities", tags=["capabilities"])
    async def discover_capabilities_endpoint(q: str | None = None, req: Request = None) -> list[dict[str, Any]]:  # type: ignore[assignment]
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
        # M2 (PRD-2026-030): entity-aware candidate narrowing — intent 命中实体时收窄候选集
        try:
            from earp_server.ontology.search import resolve_with_entities

            narrowed = await resolve_with_entities(req.app.state.engine, req.state.tenant_id, req_body.intent)
            if narrowed:
                nids = {c["capability_id"] for c in narrowed}
                narrowed_caps = [c for c in caps if c["capability_id"] in nids]
                if narrowed_caps:
                    caps = narrowed_caps
        except Exception:
            pass  # 实体识别失败不阻塞规划（planner-spec §5.1.5 MUST NOT block）
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
    async def _index_document(
        engine, tenant_id: str, kb_id: str, content: str, title: str, classification: str, metadata: dict | None = None
    ) -> dict[str, Any]:
        """Shared ingestion: dedup → create doc → chunk (KB config) → embed.

        After embedding, rebuilds the owning KB's summary embedding (doc titles
        are part of the KB summary text) — routing write-time cascade (C-8).
        """
        from sqlalchemy import text as _text

        content_hash = hashlib.md5(content.encode()).hexdigest()
        dup = await find_duplicate(engine, tenant_id, kb_id, content_hash)
        if dup:
            return {"document_id": dup, "status": "unchanged", "chunks": 0}
        doc = await create_document(engine, tenant_id, kb_id, content, title, classification, metadata=metadata)
        # chunking params come from the KB's retrieval_model config (per-KB),
        # falling back to global defaults when the KB has no config.
        chunk_rules: dict | None = None
        async with engine.connect() as conn:
            await conn.execute(_text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            row = await conn.execute(
                _text("SELECT retrieval_model FROM knowledge_bases WHERE knowledge_base_id = :kid"),
                {"kid": kb_id},
            )
            r = row.fetchone()
            if r and r.retrieval_model and r.retrieval_model.get("segmentation"):
                chunk_rules = {"segmentation": r.retrieval_model["segmentation"]}
        chunk_ids = await create_chunks(engine, tenant_id, doc["document_id"], content, rules=chunk_rules)
        await embed_chunks(engine, tenant_id, chunk_ids)
        await build_routing_index(engine, tenant_id, kb_ids=[kb_id])
        return {"document_id": doc["document_id"], "status": "indexed", "chunks": len(chunk_ids)}

    @app.post("/knowledge/documents", status_code=201, tags=["knowledge"])
    async def upload_document(req_body: DocUpload, req: Request) -> dict[str, Any]:
        return await _index_document(
            req.app.state.engine,
            req.state.tenant_id,
            req_body.knowledge_base_id,
            req_body.content,
            req_body.title,
            req_body.data_classification,
            metadata=req_body.metadata,
        )

    @app.post("/knowledge/documents/upload", status_code=201, tags=["knowledge"])
    async def upload_document_file(
        req: Request,
        file: UploadFile = File(...),
        knowledge_base_id: str = Form(...),
        data_classification: str = Form("internal"),
        metadata: str = Form("{}"),  # JSON string of manual doc metadata
    ) -> dict[str, Any]:
        """Multipart upload: .docx / .pdf / txt / md / csv / json / html."""
        try:
            meta = json.loads(metadata) if metadata.strip() else {}
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"metadata 必须是 JSON 字符串: {exc}") from exc
        data = await file.read()
        try:
            content = extract_text(file.filename or "", data)
        except FileParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return await _index_document(
            req.app.state.engine,
            req.state.tenant_id,
            knowledge_base_id,
            content,
            file.filename or "",
            data_classification,
            metadata=meta,
        )

    @app.post("/knowledge/search", tags=["knowledge"])
    async def search_knowledge(req_body: SearchQuery, req: Request) -> list[dict[str, Any]]:
        """Knowledge search. No explicit KB/DD scope → soft-routing + three-layer
        retrieval (ontology profile/graph + chunk, RRF recall fusion, P2). Explicit
        scope keeps current in-scope chunk semantics.
        """
        engine = req.app.state.engine
        bus = req.app.state.eventbus
        q_emb = await embed_query(req_body.query)
        kb_ids = req_body.knowledge_base_ids
        if kb_ids is None and req_body.data_domain_ids is None:
            routed = await route_query(
                engine, req.state.tenant_id, req_body.query, q_emb, req.state.role_id
            )
            cand_dds = [dd["data_domain_id"] for dd in routed["candidate_dds"]]
            cand_kbs = [kb["knowledge_base_id"] for kb in routed["candidate_kbs"]]
            if cand_dds:
                # 有候选 DD → 三层检索：L1/L2 实体层限 DD，L3 chunk 限 KB
                # （candidate_kbs 空 → search_chunks 自动回退 DD，决策 D4）
                logger.info(
                    "search soft-routing + ontology: query=%r candidate_dds=%s candidate_kbs=%s fallback=%s",
                    req_body.query,
                    cand_dds,
                    cand_kbs,
                    routed["fallback_used"],
                )
                from earp_server.ontology.search import knowledge_search

                return await knowledge_search(
                    engine,
                    req.state.tenant_id,
                    req_body.query,
                    embedding=q_emb,
                    role_id=req.state.role_id,
                    data_domain_ids=cand_dds,
                    knowledge_base_ids=cand_kbs or None,
                    top_k=req_body.top_k,
                    embedding_dim=req.app.state.settings.embedding_dim,
                    query_text=req_body.query,
                    mode=req_body.mode,
                    threshold=req_body.threshold,
                    metadata_filters=req_body.metadata_filters,
                    eventbus=bus,
                    rerank=True,
                    rerank_top_n=req.app.state.settings.rerank_top_n,
                )
            # 无候选 DD → 三层检索兜底（决策 D4 语义 + 2026-08-18 FDE 修复：
            # 此前纯 chunk 兜底 → 实体类查询（如「张建国」）profile/graph 完全不触发；
            # 现在实体层按角色允许域、chunk 层按候选 KB/角色域，权限不变）
            kb_ids = cand_kbs or None
            logger.info(
                "search soft-routing fallback: query=%r no candidate DD → three-layer fallback (candidate_kbs=%s)",
                req_body.query,
                cand_kbs,
            )
            from earp_server.ontology.search import knowledge_search

            return await knowledge_search(
                engine,
                req.state.tenant_id,
                req_body.query,
                embedding=q_emb,
                role_id=req.state.role_id,
                knowledge_base_ids=kb_ids,
                top_k=req_body.top_k,
                embedding_dim=req.app.state.settings.embedding_dim,
                query_text=req_body.query,
                mode=req_body.mode,
                threshold=req_body.threshold,
                metadata_filters=req_body.metadata_filters,
                eventbus=bus,
                rerank=True,
                rerank_top_n=req.app.state.settings.rerank_top_n,
            )
        return await search_chunks(
            engine,
            req.state.tenant_id,
            q_emb,
            req.state.role_id,
            req_body.top_k,
            eventbus=bus,
            embedding_dim=req.app.state.settings.embedding_dim,
            knowledge_base_ids=kb_ids,
            data_domain_ids=req_body.data_domain_ids,
            threshold=req_body.threshold,
            query_text=req_body.query,
            mode=req_body.mode,
            metadata_filters=req_body.metadata_filters,
            rerank=True,
            rerank_top_n=req.app.state.settings.rerank_top_n,
        )

    # ── Routing: debug view + index rebuild (enterprise-retrieval Phase 1) ──
    @app.post("/knowledge/routing/debug", tags=["knowledge"])
    async def routing_debug_endpoint(req_body: RoutingDebugRequest, req: Request) -> dict[str, Any]:
        """Routing debug view: DD keyword/vector lanes → candidate DDs (permitted)
        → candidate KBs, plus description coverage + freshness for every domain.
        """
        q_emb = await embed_query(req_body.query)
        return await route_debug(
            req.app.state.engine,
            req.state.tenant_id,
            req_body.query,
            q_emb,
            req.state.role_id,
            req_body.top_n,
            req_body.top_k,
        )

    @app.post("/knowledge/routing/rebuild", tags=["knowledge"])
    async def routing_rebuild_endpoint(req_body: RoutingRebuildRequest, req: Request) -> dict[str, Any]:
        """Manually rebuild routing embeddings (None = all domains/KBs).
        Idempotent: unchanged aggregate texts are skipped (hash check).
        """
        stats = await build_routing_index(
            req.app.state.engine,
            req.state.tenant_id,
            dd_ids=req_body.data_domain_ids,
            kb_ids=req_body.knowledge_base_ids,
        )
        return stats

    # ── Doc-level metadata editing (enterprise-retrieval design §4, C-9) ──
    @app.patch("/knowledge/documents/{doc_id}/metadata", tags=["knowledge"])
    async def update_doc_metadata_endpoint(doc_id: str, req_body: MetadataUpdate, req: Request) -> dict[str, Any]:
        """Edit a document's manual metadata (schema-validated, auto fields rejected)."""
        try:
            updated = await update_document_metadata(
                req.app.state.engine, req.state.tenant_id, doc_id, req_body.metadata
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="document not found")
        return {"document_id": doc_id, "metadata": updated}

    # ── Chunking preview (no persistence — test chunking params before upload) ──
    @app.post("/knowledge/chunks/preview", tags=["knowledge"])
    async def preview_chunks(req_body: ChunkPreviewRequest, req: Request) -> dict[str, Any]:
        rules = {
            "pre_processing_rules": [
                {"id": "remove_extra_spaces", "enabled": req_body.remove_extra_spaces},
            ],
            "segmentation": {
                "separator": req_body.separator,
                "separators": req_body.separators,
                "max_tokens": req_body.max_tokens,
                "chunk_overlap": req_body.chunk_overlap,
            },
        }
        preview = build_preview(req_body.content, rules)
        return {"chunks": preview, "total": len(preview)}

    # ── Knowledge Admin (PRD-2026-028 §6.5/§6.6) ──
    @app.post("/knowledge/bases", status_code=201, tags=["knowledge"])
    async def create_kb_endpoint(req_body: KBCreate, req: Request) -> dict[str, Any]:
        return await create_kb(
            req.app.state.engine,
            req.state.tenant_id,
            req_body.name,
            req_body.data_domain_id,
            req_body.description,
            retrieval_model=req_body.retrieval_model,
            indexing_technique=req_body.indexing_technique,
            metadata_schema=req_body.metadata_schema,
            summary_text=req_body.summary_text,
        )

    @app.get("/knowledge/bases", tags=["knowledge"])
    async def list_kbs_endpoint(req: Request, data_domain_id: str | None = None) -> list[dict[str, Any]]:
        return await list_kbs(req.app.state.engine, req.state.tenant_id, data_domain_id)

    @app.delete("/knowledge/bases/{kb_id}", status_code=204, tags=["knowledge"])
    async def delete_kb_endpoint(kb_id: str, req: Request) -> None:
        deleted = await delete_kb(req.app.state.engine, req.state.tenant_id, kb_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="KB not found")

    @app.patch("/knowledge/bases/{kb_id}", tags=["knowledge"])
    async def update_kb_endpoint(kb_id: str, req_body: KBUpdate, req: Request) -> dict[str, Any]:
        """Edit KB basic attributes (name / data domain / description / indexing)."""
        try:
            updated = await update_kb(
                req.app.state.engine,
                req.state.tenant_id,
                kb_id,
                name=req_body.name,
                data_domain_id=req_body.data_domain_id,
                description=req_body.description,
                indexing_technique=req_body.indexing_technique,
                metadata_schema=req_body.metadata_schema,
                summary_text=req_body.summary_text,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="KB not found")
        return updated

    @app.patch("/knowledge/bases/{kb_id}/retrieval", tags=["knowledge"])
    async def update_kb_retrieval_endpoint(kb_id: str, req_body: KBRetrievalUpdate, req: Request) -> dict[str, Any]:
        """Save per-KB retrieval/chunking config (used by Test Retrieval '保存到KB')."""
        updated = await update_kb_retrieval(
            req.app.state.engine,
            req.state.tenant_id,
            kb_id,
            req_body.retrieval_model,
            req_body.indexing_technique,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="KB not found")
        return updated

    @app.post("/knowledge/bases/{kb_id}/reindex", tags=["knowledge"])
    async def reindex_kb_endpoint(kb_id: str, req: Request) -> dict[str, Any]:
        """Re-chunk + re-embed all documents of a KB using its saved chunking config."""
        stats = await reindex_kb(req.app.state.engine, req.state.tenant_id, kb_id)
        if stats is None:
            raise HTTPException(status_code=404, detail="KB not found")
        return stats

    @app.get("/knowledge/bases/{kb_id}/documents", tags=["knowledge"])
    async def list_documents_endpoint(kb_id: str, req: Request) -> list[dict[str, Any]]:
        return await list_documents(req.app.state.engine, req.state.tenant_id, kb_id)

    @app.patch("/knowledge/documents/{doc_id}", tags=["knowledge"])
    async def update_doc_class_endpoint(doc_id: str, req_body: DocClassUpdate, req: Request) -> dict[str, Any]:
        updated = await update_document_classification(
            req.app.state.engine, req.state.tenant_id, doc_id, req_body.data_classification
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return updated

    @app.get("/knowledge/documents/{doc_id}", tags=["knowledge"])
    async def get_doc_detail_endpoint(doc_id: str, req: Request) -> dict[str, Any]:
        detail = await get_document_detail(req.app.state.engine, req.state.tenant_id, doc_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return detail

    @app.patch("/knowledge/documents/{doc_id}/status", tags=["knowledge"])
    async def update_doc_status_endpoint(doc_id: str, req_body: DocStatusUpdate, req: Request) -> dict[str, Any]:
        if req_body.status not in ("active", "disabled"):
            raise HTTPException(status_code=400, detail="status must be active|disabled")
        updated = await update_document_status(
            req.app.state.engine, req.state.tenant_id, doc_id, req_body.status
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return updated

    @app.put("/knowledge/documents/{doc_id}/process-rule", tags=["knowledge"])
    async def save_doc_process_rule_endpoint(doc_id: str, req_body: DocProcessRule, req: Request) -> dict[str, Any]:
        saved = await save_document_process_rule(
            req.app.state.engine, req.state.tenant_id, doc_id, req_body.rules
        )
        if saved is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return saved

    @app.post("/knowledge/documents/{doc_id}/suggest-separators", tags=["knowledge"])
    async def suggest_doc_separators(doc_id: str, req: Request) -> dict[str, Any]:
        """Analyze the document's structure and suggest a priority-ordered separator list."""
        from sqlalchemy import text as _text

        engine = req.app.state.engine
        async with engine.connect() as conn:
            await conn.execute(_text(f"SET LOCAL earp.tenant_id = '{req.state.tenant_id}'"))
            row = await conn.execute(_text("SELECT content FROM documents WHERE document_id = :did"), {"did": doc_id})
            r = row.fetchone()
            if r is None:
                raise HTTPException(status_code=404, detail="Document not found")
            content = r.content or ""
        seps = suggest_separators(content)
        return {
            "document_id": doc_id,
            "separators": seps,
            "display": [s.replace("\n", "\\n") for s in seps],
        }

    @app.post("/knowledge/documents/{doc_id}/preview", tags=["knowledge"])
    async def preview_doc_chunks(doc_id: str, req_body: DocPreviewRequest, req: Request) -> dict[str, Any]:
        """Preview chunking for ONE document's content with the given params."""
        from sqlalchemy import text as _text

        engine = req.app.state.engine
        async with engine.connect() as conn:
            await conn.execute(_text(f"SET LOCAL earp.tenant_id = '{req.state.tenant_id}'"))
            row = await conn.execute(_text("SELECT content FROM documents WHERE document_id = :did"), {"did": doc_id})
            r = row.fetchone()
            if r is None:
                raise HTTPException(status_code=404, detail="Document not found")
            content = r.content or ""
        rules = {
            "pre_processing_rules": [
                {"id": "remove_extra_spaces", "enabled": req_body.remove_extra_spaces},
            ],
            "segmentation": {
                "separator": req_body.separator,
                "separators": req_body.separators,
                "max_tokens": req_body.max_tokens,
                "chunk_overlap": req_body.chunk_overlap,
            },
        }
        preview = build_preview(content, rules)
        return {"document_id": doc_id, "chunks": preview, "total": len(preview)}

    @app.post("/knowledge/documents/{doc_id}/reindex", tags=["knowledge"])
    async def reindex_doc_endpoint(doc_id: str, req: Request) -> dict[str, Any]:
        """Re-chunk + re-embed ONE document (uses its saved rule, fallback KB config)."""
        stats = await reindex_document(req.app.state.engine, req.state.tenant_id, doc_id)
        if stats is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return stats

    @app.delete("/knowledge/documents/{doc_id}", status_code=204, tags=["knowledge"])
    async def delete_doc_endpoint(doc_id: str, req: Request) -> None:
        deleted = await delete_document(req.app.state.engine, req.state.tenant_id, doc_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Document not found")

    # ── Data Domains Admin (PRD-2026-028 §6.6) ──
    async def _require_admin(req: Request) -> None:
        """管理端门禁（2026-08-18 越权修复）：仅 is_admin 角色可变更管理数据。"""
        from earp_server.policy.roles_service import is_admin_role

        if not await is_admin_role(req.app.state.engine, req.state.tenant_id, req.state.role_id):
            raise HTTPException(status_code=403, detail="仅 Admin 角色可执行此操作")

    @app.get("/api/data-domains", tags=["knowledge"])
    async def list_data_domains_endpoint(req: Request) -> list[dict[str, Any]]:
        return await list_data_domains(req.app.state.engine, req.state.tenant_id)

    @app.post("/api/data-domains", status_code=201, tags=["knowledge"])
    async def create_data_domain_endpoint(req_body: DataDomainCreate, req: Request) -> dict[str, Any]:
        await _require_admin(req)
        return await create_data_domain(
            req.app.state.engine,
            req.state.tenant_id,
            req_body.data_domain_id,
            req_body.name,
            req_body.data_classification,
            req_body.description,
            req_body.owner,
        )

    @app.delete("/api/data-domains/{data_domain_id}", status_code=200, tags=["knowledge"])
    async def delete_data_domain_endpoint(data_domain_id: str, req: Request) -> dict[str, Any]:
        await _require_admin(req)
        try:
            return await delete_data_domain(req.app.state.engine, req.state.tenant_id, data_domain_id)
        except DataDomainInUseError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.patch("/api/data-domains/{data_domain_id}", tags=["knowledge"])
    async def update_data_domain_endpoint(
        data_domain_id: str, req_body: DataDomainUpdate, req: Request
    ) -> dict[str, Any]:
        """Edit data domain basic attributes (name / description / classification / owner / routing)."""
        await _require_admin(req)
        updated = await update_data_domain(
            req.app.state.engine,
            req.state.tenant_id,
            data_domain_id,
            name=req_body.name,
            description=req_body.description,
            data_classification=req_body.data_classification,
            owner=req_body.owner,
            routing_description=req_body.routing_description,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Data domain not found")
        return updated

    # ── AI-assisted DD routing description (C-7: LLM draft, manual confirm) ──
    @app.post("/api/data-domains/{data_domain_id}/suggest-description", tags=["knowledge"])
    async def suggest_dd_description_endpoint(data_domain_id: str, req: Request) -> dict[str, Any]:
        """Generate a routing_description draft from the domain's KB names/descriptions.

        Returns the draft + source KBs; the admin confirms/edits and saves via
        PATCH /api/data-domains/{id}. Management aid only — no test coverage
        for the LLM call itself (dev-only; Ollama required).
        """
        from sqlalchemy import text as _text

        engine = req.app.state.engine
        async with engine.connect() as conn:
            await conn.execute(_text(f"SET LOCAL earp.tenant_id = '{req.state.tenant_id}'"))
            drow = await conn.execute(
                _text("SELECT name, description FROM data_domains WHERE data_domain_id = :dd"),
                {"dd": data_domain_id},
            )
            dd = drow.fetchone()
            if dd is None:
                raise HTTPException(status_code=404, detail="Data domain not found")
            kbs = [
                f"{r.name}（{r.description}）" if r.description else r.name
                for r in await conn.execute(
                    _text(
                        "SELECT name, description FROM knowledge_bases "
                        "WHERE data_domain_id = :dd ORDER BY name"
                    ),
                    {"dd": data_domain_id},
                )
            ]
        domain_label = f"{dd.name}（{dd.description}）" if dd.description else dd.name
        kb_text = "；".join(kbs) if kbs else "（暂无知识库）"
        prompt = (
            f"请为数据域「{domain_label}」写一段检索描述（50-150字），用于语义路由："
            f"描述会被向量化后与用户查询匹配，需覆盖该域下所有知识库主题：{kb_text}。"
            '只输出 JSON：{"description": "..."}'
        )
        draft = await _llm_suggest(engine, req.state.tenant_id, req.app.state.settings, prompt)
        return {"data_domain_id": data_domain_id, "suggested_description": draft, "sources": kbs}

    # ── AI-assisted KB retrieval summary (KB parity with DD, 2026-08-09) ──
    @app.post("/knowledge/bases/{kb_id}/suggest-summary", tags=["knowledge"])
    async def suggest_kb_summary_endpoint(kb_id: str, req: Request) -> dict[str, Any]:
        """Generate a KB summary_text draft from KB name/description + doc titles.
        The admin confirms/edits and saves via PATCH /knowledge/bases/{id}.
        """
        from sqlalchemy import text as _text

        engine = req.app.state.engine
        async with engine.connect() as conn:
            await conn.execute(_text(f"SET LOCAL earp.tenant_id = '{req.state.tenant_id}'"))
            krow = await conn.execute(
                _text("SELECT name, description FROM knowledge_bases WHERE knowledge_base_id = :kid"),
                {"kid": kb_id},
            )
            kb = krow.fetchone()
            if kb is None:
                raise HTTPException(status_code=404, detail="Knowledge base not found")
            titles = [
                r.title
                for r in (await conn.execute(
                    _text(
                        "SELECT title FROM documents WHERE knowledge_base_id = :kid "
                        "AND status = 'active' AND title IS NOT NULL AND title <> '' "
                        "ORDER BY created_at LIMIT 60"
                    ),
                    {"kid": kb_id},
                )).fetchall()
            ]
        kb_label = f"{kb.name}（{kb.description}）" if kb.description else kb.name
        title_text = "；".join(titles) if titles else "（暂无文档）"
        prompt = (
            f"请为知识库「{kb_label}」写一段检索摘要（30-100字），用于语义路由定位："
            f"摘要会被向量化后与用户查询匹配，需覆盖该知识库文档主题：{title_text}。"
            '只输出 JSON：{"description": "..."}'
        )
        draft = await _llm_suggest(engine, req.state.tenant_id, req.app.state.settings, prompt)
        return {"knowledge_base_id": kb_id, "suggested_summary": draft, "sources": titles}

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

    # ── Chat Apps（工作台 · chat 智能体，P1 问答链路一期）──
    @app.get("/chat_apps", tags=["chat_apps"])
    async def list_chat_apps_ep(req: Request) -> list[dict[str, Any]]:
        return await list_chat_apps(req.app.state.engine, req.state.tenant_id)

    @app.get("/chat_apps/{chat_app_id}", tags=["chat_apps"])
    async def get_chat_app_ep(chat_app_id: str, req: Request) -> dict[str, Any]:
        app = await get_chat_app(req.app.state.engine, req.state.tenant_id, chat_app_id)
        if app is None:
            raise HTTPException(status_code=404, detail="chat app not found")
        return app

    @app.post("/chat_apps", status_code=201, tags=["chat_apps"])
    async def create_chat_app_ep(req_body: ChatAppCreate, req: Request) -> dict[str, Any]:
        try:
            return await create_chat_app(
                req.app.state.engine,
                req.state.tenant_id,
                req.state.user_id,
                req_body.name,
                req_body.description,
                bus=req.app.state.eventbus,
                system_prompt=req_body.system_prompt,
                orchestration=req_body.orchestration,
                flow_schema=req_body.flow_schema,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    @app.patch("/chat_apps/{chat_app_id}", tags=["chat_apps"])
    async def update_chat_app_ep(chat_app_id: str, req_body: ChatAppUpdate, req: Request) -> dict[str, Any]:
        try:
            app = await update_chat_app(
                req.app.state.engine,
                req.state.tenant_id,
                req.state.user_id,
                chat_app_id,
                req_body.model_dump(exclude_unset=True),
                bus=req.app.state.eventbus,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        if app is None:
            raise HTTPException(status_code=404, detail="chat app not found")
        return app

    @app.delete("/chat_apps/{chat_app_id}", status_code=204, tags=["chat_apps"])
    async def delete_chat_app_ep(chat_app_id: str, req: Request) -> None:
        ok = await delete_chat_app(
            req.app.state.engine,
            req.state.tenant_id,
            req.state.user_id,
            chat_app_id,
            bus=req.app.state.eventbus,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="chat app not found")

    @app.post("/chat_apps/{chat_app_id}/publish", tags=["chat_apps"])
    async def publish_chat_app_ep(chat_app_id: str, req: Request) -> dict[str, Any]:
        app = await publish_chat_app(
            req.app.state.engine,
            req.state.tenant_id,
            req.state.user_id,
            chat_app_id,
            bus=req.app.state.eventbus,
        )
        if app is None:
            raise HTTPException(status_code=404, detail="chat app not found")
        return app

    @app.post("/chat_apps/{chat_app_id}/chat", tags=["chat_apps"], response_model=None)
    async def chat_ep(
        chat_app_id: str, req_body: ChatRequest, req: Request
    ) -> StreamingResponse | dict[str, Any] | JSONResponse:
        """对话入口：auto = SSE 流式（现状）；flow = 声明式图执行（Chatflow F2，非流式 JSON；
        F4 human_approval 挂起 → 202）。"""
        app = await get_chat_app(req.app.state.engine, req.state.tenant_id, chat_app_id)
        if app is None:
            raise HTTPException(status_code=404, detail="chat app not found")

        if app.get("orchestration") == "flow":
            from earp_server.connector import ConnectorError
            from earp_server.orchestrator.workflow_dsl import WorkflowValidationError

            try:
                result = await flow_chat(
                    req.app.state.engine,
                    req.state.tenant_id,
                    req.state.user_id,
                    req.state.role_id,
                    app,
                    req_body.query,
                    req_body.conversation_id,
                    base_llm=req.app.state.llm,
                    settings=req.app.state.settings,
                    bus=req.app.state.eventbus,
                )
                if result.get("status") == "waiting_human":
                    # Chatflow F4: human_approval 挂起 → 202（等待人工答复）
                    return JSONResponse(status_code=202, content=result)
                return result
            except HTTPException:
                raise  # Chatflow F3: PolicyLayer 权限拒绝 403 透传（勿转 500）
            except (ConnectorError, ChatError, WorkflowValidationError) as e:
                raise HTTPException(status_code=422, detail=f"flow 执行失败：{e}") from e
            except Exception:
                logger.exception("flow chat failed")
                raise HTTPException(status_code=500, detail="flow 执行失败，请稍后重试") from None

        async def gen():
            async for line in chat_sse(
                req.app.state.engine,
                req.state.tenant_id,
                req.state.user_id,
                req.state.role_id,
                app,
                req_body.query,
                req_body.conversation_id,
                base_llm=req.app.state.llm,
                settings=req.app.state.settings,
                rate_limiter=req.app.state.rate_limiter,
                embedding_dim=req.app.state.settings.embedding_dim,
            ):
                yield line

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                # 防代理/网关缓冲：token 逐条到达，避免「几秒无输出后突然全出」
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    # ── Conversation ──
    @app.post("/conversations", status_code=201, tags=["conversations"])
    async def create_conv(req_body: ConvCreate, req: Request) -> dict[str, Any]:
        return await create_conversation(req.app.state.engine, req.state.tenant_id, req.state.user_id, req_body.title)

    @app.get("/conversations", tags=["conversations"])
    async def list_conv(limit: int = 50, offset: int = 0, req: Request = None) -> list[dict[str, Any]]:  # type: ignore[assignment]
        """Conversation list（新增端点 Q1）：对话日志/二期应用形态数据源。"""
        return await list_conversations(req.app.state.engine, req.state.tenant_id, limit, offset)

    @app.post("/conversations/{conv_id}/messages", status_code=201, tags=["conversations"])
    async def add_msg(conv_id: str, req_body: MsgAdd, req: Request) -> dict[str, Any]:
        return await add_message(
            req.app.state.engine, req.state.tenant_id, conv_id, req_body.role, req_body.content, req.state.user_id
        )

    @app.get("/conversations/{conv_id}/messages", tags=["conversations"])
    async def list_msgs(conv_id: str, limit: int = 50, offset: int = 0, req: Request = None) -> list[dict[str, Any]]:  # type: ignore[assignment]
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
