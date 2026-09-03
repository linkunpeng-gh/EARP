"""FastAPI application factory. M1 surface: sessions CRUD, invoke, capability, audit."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import pathlib
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from earp_server.admin.app_center_routes import router as app_center_router
from earp_server.admin.model_routes import router as model_routes_router
from earp_server.admin.roles_routes import router as roles_router
from earp_server.audit.consumer import audit_handler_factory
from earp_server.capability.registry import TokenBucketRateLimiter, discover, list_for_planning, seed_demo_tenant
from earp_server.capability.service import (
    CapabilityConflictError,
    capability_visible_to_role,
    create_capability,
    deprecate_capability,
    get_capability,
    update_capability,
)
from earp_server.catalog.database_resolver import DatabaseCatalogResolver
from earp_server.catalog.routes import router as catalog_router
from earp_server.causal_model_management.catalog import CatalogResolutionError
from earp_server.causal_model_management.errors import N01AError
from earp_server.causal_model_management.routes import router as causal_model_management_router
from earp_server.config import Settings
from earp_server.connector import LLMConnector
from earp_server.conversation.chat_app_service import (
    create_chat_app,
    delete_chat_app,
    favorite_app,
    get_chat_app,
    is_app_visible,
    publish_chat_app,
    search_chat_apps,
    unfavorite_app,
    update_chat_app,
)
from earp_server.conversation.chat_service import ChatError, chat_sse, flow_chat
from earp_server.conversation.conversation_service import (
    add_message,
    conversation_exists,
    conversation_visible,
    create_conversation,
    get_messages,
    list_conversations,
)
from earp_server.conversation.flow_runs import get_conversation_runs, list_runs
from earp_server.gateway.api_keys import create_api_key, list_api_keys, revoke_api_key, touch_api_key
from earp_server.gateway.auth import JWTMiddleware, create_token
from earp_server.gateway.input_guard import sanitize_body
from earp_server.infra.db import build_engine, check_db
from earp_server.infra.eventbus import CloudEvent, EventBus
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
from earp_server.planner.blueprint_discovery import BlueprintDiscoveryError
from earp_server.planner.blueprint_entry import BlueprintEntryError, BlueprintPlanningEntry, PlanningEntryRequest
from earp_server.planner.task_planner import SimpleTaskPlanner
from earp_server.policy.app_access_service import is_is_admin
from earp_server.runtime.invoke import router as invoke_router
from earp_server.runtime.session_service import close_session, create_session, get_session, list_sessions
from earp_server.schemas.sessions import SessionCreateRequest, SessionResponse

APP_TITLE = "EARP Server"
APP_VERSION = "0.1.0"
logger = logging.getLogger(__name__)


class PlanRequest(BaseModel):
    intent: str


class BlueprintPlanningEntryRequest(BaseModel):
    """T07's explicit Case A entry; it is intentionally not a ``/plan`` variant."""

    text: str = Field(min_length=1, max_length=500)


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


class CapabilityCreate(BaseModel):
    """能力注册（tech-debt #14）。capability_id 可省（自动生成 cap-{domain}-{name}）；
    execution = {"adapter": "<白名单>", "params": {...}} 声明「怎么执行」（通用执行器消费）。"""

    domain: str
    name: str
    type: str  # query | command
    capability_id: str | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    required_permissions: list[str] | None = None
    version: str = "1.0.0"
    execution: dict | None = None
    visible_roles: list[str] | None = None


class CapabilityUpdate(BaseModel):
    """能力更新（全字段可选；status 不可在此改，停用走 DELETE）。"""

    domain: str | None = None
    name: str | None = None
    type: str | None = None
    input_schema: dict | None = None
    output_schema: dict | None = None
    required_permissions: list[str] | None = None
    version: str | None = None
    execution: dict | None = None
    visible_roles: list[str] | None = None


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
    category: str | None = None  # 应用中心：业务分类（租户词表内，发布必填）
    tags: list[str] | None = None  # 应用中心：自由标签


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
    category: str | None = None
    tags: list[str] | None = None


class PublishBody(BaseModel):
    category: str | None = None
    tags: list[str] | None = None


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    conversation_id: str | None = None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class LoginRequest(BaseModel):
    tenant_id: str
    user_id: str
    role_id: str


class StreamRequest(BaseModel):
    prompt: str
    system: str = ""
    session_id: str = ""


class CopilotAssistRequest(BaseModel):
    page_id: str
    intent: str = "explain"  # explain | diagnose | suggest | autofill | apply
    query: str = Field(min_length=1)
    form_state: dict[str, Any] = {}
    conversation_id: str | None = None


async def _service_role(engine, tenant_id: str, app: dict[str, Any]) -> str:
    """对外 API 调用（tech-debt #18 D5）：服务调用无用户/角色——role_id 取应用创建者
    当前角色（tenant_account_joins.current_role_id）；解析不到（created_by 空/用户无角色）→ 空。
    命令审批（F4 human_approval）与角色无关——API 调用遇挂起照常 202，恢复靠 conversation_id。
    """
    created_by = app.get("created_by")
    if not created_by:
        return ""
    from sqlalchemy import text

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = (
            await conn.execute(
                text("SELECT current_role_id FROM tenant_account_joins WHERE tenant_id = :t AND user_id = :u"),
                {"t": tenant_id, "u": created_by},
            )
        ).first()
    return row[0] if row and row[0] else ""


def _api_audit(
    req: Request,
    event_type: str,
    *,
    status_code: int = 200,
    elapsed_ms: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """对外 API 审计（tech-debt #18 D6）：earp.api.* 事件，fire-and-forget 走 EventBus。

    data 含 app_id/key_id/tenant（服务身份）/http_status/耗时；flow 完成事件额外带
    execution_id（流程执行关联，audit_logs 可回溯 flow_runs）。
    """
    bus = getattr(req.app.state, "eventbus", None)
    if bus is None:
        return
    data: dict[str, Any] = {
        "entity_type": "chat_app",
        "entity_id": getattr(req.state, "chat_app_id", ""),
        "user_id": getattr(req.state, "user_id", ""),
        "api_key_id": getattr(req.state, "api_key_id", ""),
        "chat_app_id": getattr(req.state, "chat_app_id", ""),
        "http_status": status_code,
        **(extra or {}),
    }
    if elapsed_ms is not None:
        data["elapsed_ms"] = elapsed_ms
    bus.publish(
        CloudEvent(
            type=event_type,
            source="earp-server/gateway",
            tenant_id=getattr(req.state, "tenant_id", ""),
            data=data,
        )
    )


async def _chat_dispatch(req: Request, chat_app_id: str, req_body: ChatRequest, app: dict[str, Any] | None = None):
    """对话分发（内部 /chat_apps/{id}/chat 与对外 /api/v1/chat-apps/{id}/chat 共用）：
    auto = SSE 流式；flow = 声明式图执行（Chatflow F2 非流式 JSON；F4 human_approval 挂起 → 202）。
    调用方负责前置校验（内部端点：无；对外端点：密钥绑定 + 已发布，见 api_chat_ep）。
    """
    if app is None:
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
            # F7 (Task 2 D4): 422 统一 + 错误分类码（ConnectorFetchError 已归一进
            # ConnectorError → 连接类不再 fallthrough 500）
            code = getattr(e, "code", None)
            detail = f"flow 执行失败：{e}" if not code else f"flow 执行失败[{code}]：{e}"
            raise HTTPException(status_code=422, detail=detail) from e
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


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.monotonic() - started_at) * 1000))


def _dev_ecmc_catalog_entries() -> list[Any]:
    """Dev/test-only fake catalog entries for ECMC page testing.

    Mirrors the frontend `?catalog=fake` adapter (same stable_ids / domains) so the
    full N01B page flow can be exercised against a real server.  Data domain uses
    the stable-id convention (`production` / `equipment`) which the service stores
    as `causal_models.data_domain_id`.  Never registered when the env flag is off;
    production keeps the fail-closed `UnavailableCatalogResolver`.
    """
    from earp_server.causal_model_management.catalog import ResolvedCatalogRef

    rows: list[tuple[str, str, str]] = [
        ("data_domain", "production", "production"),
        ("data_domain", "equipment", "equipment"),
        ("entity_type", "entity.mine", "production"),
        ("entity_type", "entity.haulage_system", "production"),
        ("entity_type", "entity.equipment_group", "equipment"),
        ("relation_type", "relation.affects", "production"),
        ("relation_type", "relation.has_subsystem", "production"),
        ("relation_type", "relation.has_equipment_group", "production"),
        ("metric", "metric.production_output", "production"),
        ("metric", "metric.haulage_cycle_time", "production"),
        ("metric", "metric.haulage_queue_time", "production"),
        ("metric", "metric.equipment_availability", "equipment"),
        ("unit", "minute", "production"),
        ("unit", "ton", "production"),
        ("unit", "ratio", "production"),
        ("aggregation", "mean", "production"),
        ("aggregation", "sum_over_production_day", "production"),
        ("aggregation", "availability_over_production_day", "production"),
        ("time_window_schema", "daily_window", "production"),
        ("binding_template", "context_entity", "production"),
        ("binding_template", "outbound_relation", "production"),
        ("capability_contract", "contract.read_production_output", "production"),
        ("capability_contract", "contract.read_haulage_cycle", "production"),
        ("capability_contract", "contract.read_haulage_quality", "production"),
        ("capability_contract", "contract.read_equipment_health", "equipment"),
        ("rule_schema", "direction_rule", "production"),
        ("rule_schema", "threshold_rule", "production"),
    ]
    return [
        ResolvedCatalogRef(
            kind=kind,
            stable_id=stable_id,
            version="v1",
            content_hash=(stable_id.encode().hex() + "0" * 64)[:64],
            status="active",
            data_domain_id=domain,
            semantic_schema_version=f"{kind}/v1",
        )
        for kind, stable_id, domain in rows
    ]


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    init_all(cfg)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        app.state.settings = cfg
        app.state.engine = build_engine(cfg)
        # Source adapters are injected by deployment/test wiring.  An empty
        # registry is intentional: without a real or test adapter, registration
        # remains unavailable and fails closed.
        app.state.catalog_source_adapters = {}
        # The real catalog manifest/owner is intentionally unsigned.  Production
        # fails closed; contract tests explicitly replace this with the fake.
        # Dev/test page testing: EARP_ECMC_TEST_CATALOG=1 registers the fake
        # catalog (mirrors the frontend ?catalog=fake adapter) so N01B writes work.
        app.state.n01a_catalog_resolver = DatabaseCatalogResolver(app.state.engine)
        if cfg.app_env in ("dev", "test") and os.environ.get("EARP_ECMC_TEST_CATALOG") == "1":
            try:
                from earp_server.causal_model_management.catalog import FakeCatalogResolver

                app.state.n01a_catalog_resolver = FakeCatalogResolver(_dev_ecmc_catalog_entries())
                # Compiler requires active StepType pins (knowledge_query/output)。
                # step_types 平台表仅授予 earp_app SELECT，需用 migration 超管连接种子（幂等）。
                from sqlalchemy import text as _text
                from sqlalchemy.ext.asyncio import create_async_engine

                mgr_engine = create_async_engine(cfg.migration_database_url)
                try:
                    async with mgr_engine.begin() as conn:
                        await conn.execute(
                            _text(
                                "INSERT INTO step_types (type_id, type_name, is_core) VALUES "
                                "('step-knowledge-query','knowledge_query',true),('step-output','output',true) "
                                "ON CONFLICT (type_id) DO NOTHING"
                            )
                        )
                        await conn.execute(
                            _text(
                                "INSERT INTO step_type_versions "
                                "(step_type_version_id,type_id,version,handler_version,handler_hash,params_schema,"
                                "semantic_contract_version,status) VALUES "
                                "('stv-knowledge-query-v1','step-knowledge-query','v1','h-v1',:h1,'{}'::jsonb,'v1','active'),"
                                "('stv-output-v1','step-output','v1','h-v1',:h2,'{}'::jsonb,'v1','active') "
                                "ON CONFLICT (step_type_version_id) DO NOTHING"
                            ),
                            {"h1": "a" * 64, "h2": "b" * 64},
                        )
                finally:
                    await mgr_engine.dispose()
                logger.info("EARP_ECMC_TEST_CATALOG=1: fake ECMC catalog enabled (dev/test only)")
            except Exception:  # noqa: BLE001
                logger.warning("ECMC fake catalog init failed — keeping fail-closed resolver", exc_info=True)
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
        runtime_models: dict = {}
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
        # Copilot 专用 LLM（轻量快速模型，独立于主聊天模型）
        copilot_config = runtime_models.get("copilot") if runtime_models else None
        if copilot_config:
            copilot_llm = LLMConnector(cfg, rate_limiter=app.state.rate_limiter, model_override=copilot_config)
            logger.info(
                "copilot_llm: using DB config provider=%s model=%s",
                copilot_config.get("provider"),
                copilot_config.get("model_name"),
            )
        else:
            copilot_llm = LLMConnector(
                cfg,
                rate_limiter=app.state.rate_limiter,
                model_override={"provider": "ollama", "model_name": cfg.copilot_model},
            )
            logger.info("copilot_llm: using default model=%s", cfg.copilot_model)
        app.state.copilot_llm = copilot_llm
        if cfg.app_env in ("dev", "test"):
            # in-process audit: subscribe handler to local EventBus
            # (prod uses independent audit worker process — see entrypoints/audit.py)
            app.state.eventbus.subscribe("earp.execution.*", audit_handler_factory(app.state.engine))
            app.state.eventbus.subscribe("earp.chat_app.*", audit_handler_factory(app.state.engine))
            # Chatflow F3: capability 节点审计（capability.call 层事件 → audit_logs）
            app.state.eventbus.subscribe("earp.capability.*", audit_handler_factory(app.state.engine))
            # 命令审批流（Task 4）：审批决策/超时审计 earp.approval.*
            app.state.eventbus.subscribe("earp.approval.*", audit_handler_factory(app.state.engine))
            # tech-debt #18 (D6): 对外 API 调用审计（earp.api.*）
            app.state.eventbus.subscribe("earp.api.*", audit_handler_factory(app.state.engine))
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

    @app.exception_handler(N01AError)
    async def n01a_error_handler(request: Request, error: N01AError) -> JSONResponse:
        correlation_id = getattr(request.state, "n01a_correlation_id", f"corr-{uuid.uuid4().hex}")
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "correlation_id": correlation_id,
                    "details": error.details,
                }
            },
            headers={"X-Correlation-Id": correlation_id},
        )

    @app.exception_handler(CatalogResolutionError)
    async def n01a_catalog_error_handler(request: Request, error: CatalogResolutionError) -> JSONResponse:
        correlation_id = getattr(request.state, "n01a_correlation_id", f"corr-{uuid.uuid4().hex}")
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "correlation_id": correlation_id,
                    "details": {"catalog_ref": error.ref.model_dump(mode="json")},
                }
            },
            headers={"X-Correlation-Id": correlation_id},
        )

    @app.exception_handler(RequestValidationError)
    async def n01a_request_validation_handler(request: Request, error: RequestValidationError):
        if not request.url.path.startswith("/v1/ecmc/causal-models") and not request.url.path.startswith(
            "/v1/ecmc/catalog-change-requests"
        ):
            return await request_validation_exception_handler(request, error)
        correlation_id = getattr(request.state, "n01a_correlation_id", f"corr-{uuid.uuid4().hex}")
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "REQUEST_SCHEMA_INVALID",
                    "message": "The request does not match the N01A API contract.",
                    "correlation_id": correlation_id,
                    "details": {"errors": error.errors()},
                }
            },
            headers={"X-Correlation-Id": correlation_id},
        )

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
    async def correlation_id_header(request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-Id") or f"corr-{uuid.uuid4().hex}"
        request.state.n01a_correlation_id = correlation_id
        response = await call_next(request)
        response.headers["X-Correlation-Id"] = correlation_id
        return response

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
    app.include_router(app_center_router)
    app.include_router(causal_model_management_router)
    app.include_router(catalog_router)

    # ── ECMC dev-only compile driver（N01B 页面测试）──
    # 真实架构中 compile running→success 由 outbox 消费进程完成；本仓库尚无该
    # 消费进程，页面测试时编译会停在 running。此路由仅在 dev/test +
    # EARP_ECMC_TEST_CATALOG=1 下启用，等价于测试里直接调用 complete_attempt，
    # 生产保持 404。
    @app.post(
        "/v1/ecmc/_dev/complete-compile/{compile_id}",
        tags=["ecmc-causal-model-management", "ecmc-dev"],
    )
    async def dev_complete_compile(compile_id: str, request: Request) -> dict[str, Any]:
        if request.app.state.settings.app_env not in ("dev", "test") or os.environ.get("EARP_ECMC_TEST_CATALOG") != "1":
            raise HTTPException(status_code=404, detail="dev compile driver is disabled")
        from earp_server.causal_model_management.compiler import CandidateCompileService
        from earp_server.causal_model_management.service import ActorContext

        actor = ActorContext(
            tenant_id=request.state.tenant_id,
            actor_id=request.state.user_id,
            role_id=request.state.role_id,
            correlation_id=request.state.n01a_correlation_id,
        )
        result = await CandidateCompileService(
            request.app.state.engine, request.app.state.n01a_catalog_resolver
        ).complete_attempt(actor, compile_id)
        return result

    # ── Capability Registry ──
    @app.post("/capabilities", status_code=201, tags=["capabilities"])
    async def register_capability_endpoint(req: Request, body: CapabilityCreate | None = None) -> dict[str, Any]:
        if body is None:
            # 向后兼容（老「Register Demo」按钮，无 gate 历史语义保留）：无 body → seed demo 租户基线。
            # 自定义注册（有 body）不 seed——副作用不得先于鉴权（2026-08-21 review 修复 #2）。
            await seed_demo_tenant(req.app.state.engine, req.state.tenant_id)
            return {"capability_id": "cap-demo-echo", "status": "registered"}
        await _require_admin(req)
        try:
            cap = await create_capability(
                req.app.state.engine,
                req.state.tenant_id,
                domain=body.domain,
                name=body.name,
                type=body.type,
                capability_id=body.capability_id,
                input_schema=body.input_schema,
                output_schema=body.output_schema,
                required_permissions=body.required_permissions,
                version=body.version,
                execution=body.execution,
                visible_roles=body.visible_roles,
                bus=req.app.state.eventbus,
                user_id=req.state.user_id,
            )
        except CapabilityConflictError as e:
            # 重复创建 → 409（区别于校验错误 422，REST 语义）
            raise HTTPException(status_code=409, detail=str(e)) from e
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return cap

    @app.get("/capabilities/{capability_id}", tags=["capabilities"])
    async def get_capability_endpoint(capability_id: str, req: Request) -> dict[str, Any]:
        cap = await get_capability(req.app.state.engine, req.state.tenant_id, capability_id)
        if cap is None:
            raise HTTPException(status_code=404, detail="capability not found")
        # 角色可见性（review 修复 #4）：列表看不见的能力，知道 id 也拿不到全量声明
        # （不满足 → 404，不暴露存在性，M3 live 端点先例）
        if not await capability_visible_to_role(
            req.app.state.engine, req.state.tenant_id, capability_id, req.state.role_id
        ):
            raise HTTPException(status_code=404, detail="capability not found")
        return cap

    @app.patch("/capabilities/{capability_id}", tags=["capabilities"])
    async def update_capability_endpoint(capability_id: str, body: CapabilityUpdate, req: Request) -> dict[str, Any]:
        await _require_admin(req)
        try:
            cap = await update_capability(
                req.app.state.engine,
                req.state.tenant_id,
                capability_id,
                domain=body.domain,
                name=body.name,
                type=body.type,
                input_schema=body.input_schema,
                output_schema=body.output_schema,
                required_permissions=body.required_permissions,
                version=body.version,
                execution=body.execution,
                visible_roles=body.visible_roles,
                bus=req.app.state.eventbus,
                user_id=req.state.user_id,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        if cap is None:
            raise HTTPException(status_code=404, detail="capability not found")
        return cap

    @app.delete("/capabilities/{capability_id}", status_code=200, tags=["capabilities"])
    async def deprecate_capability_endpoint(capability_id: str, req: Request) -> dict[str, Any]:
        await _require_admin(req)
        cap = await deprecate_capability(
            req.app.state.engine,
            req.state.tenant_id,
            capability_id,
            bus=req.app.state.eventbus,
            user_id=req.state.user_id,
        )
        if cap is None:
            raise HTTPException(status_code=404, detail="capability not found")
        return cap

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
    @app.post("/v1/ecmc/planning/entry", tags=["ecmc", "planner"])
    async def blueprint_planning_entry_endpoint(
        req_body: BlueprintPlanningEntryRequest, req: Request
    ) -> dict[str, Any]:
        """Resolve the fixed Case A request to one immutable Blueprint goal.

        T07 intentionally stops before Prepare; no Provider/Evidence task is
        created at this boundary.
        """
        try:
            result = await BlueprintPlanningEntry(req.app.state.engine).resolve(
                PlanningEntryRequest(
                    text=req_body.text,
                    tenant_id=req.state.tenant_id,
                    role_id=req.state.role_id,
                )
            )
        except (BlueprintEntryError, BlueprintDiscoveryError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return result.as_dict()

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
            routed = await route_query(engine, req.state.tenant_id, req_body.query, q_emb, req.state.role_id)
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
        updated = await update_document_status(req.app.state.engine, req.state.tenant_id, doc_id, req_body.status)
        if updated is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return updated

    @app.put("/knowledge/documents/{doc_id}/process-rule", tags=["knowledge"])
    async def save_doc_process_rule_endpoint(doc_id: str, req_body: DocProcessRule, req: Request) -> dict[str, Any]:
        saved = await save_document_process_rule(req.app.state.engine, req.state.tenant_id, doc_id, req_body.rules)
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
                    _text("SELECT name, description FROM knowledge_bases WHERE data_domain_id = :dd ORDER BY name"),
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
                for r in (
                    await conn.execute(
                        _text(
                            "SELECT title FROM documents WHERE knowledge_base_id = :kid "
                            "AND status = 'active' AND title IS NOT NULL AND title <> '' "
                            "ORDER BY created_at LIMIT 60"
                        ),
                        {"kid": kb_id},
                    )
                ).fetchall()
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

    # ── Chat Apps（工作台 · chat 智能体，P1 问答链路一期；应用中心：搜索/筛选/收藏/可见性，D4）──
    @app.get("/chat_apps", tags=["chat_apps"])
    async def list_chat_apps_ep(
        req: Request,
        q: str | None = None,
        type: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        sort: str = "latest",
        fav: bool = False,
        status: str | None = None,  # 缺省=全部（工作台草稿可见）；published=仅已发布（应用中心）
    ) -> list[dict[str, Any]]:
        is_admin = await is_is_admin(req.app.state.engine, req.state.tenant_id, req.state.role_id)
        return await search_chat_apps(
            req.app.state.engine,
            req.state.tenant_id,
            role_id=req.state.role_id,
            is_admin=is_admin,
            user_id=req.state.user_id,
            q=q,
            app_type=type,
            category=category,
            tag=tag,
            sort=sort,
            fav=fav,
            status=status,
        )

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
                category=req_body.category,
                tags=req_body.tags,
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
    async def publish_chat_app_ep(
        chat_app_id: str, req: Request, req_body: PublishBody | None = None
    ) -> dict[str, Any]:
        body = req_body or PublishBody()
        try:
            app = await publish_chat_app(
                req.app.state.engine,
                req.state.tenant_id,
                req.state.user_id,
                chat_app_id,
                bus=req.app.state.eventbus,
                category=body.category,
                tags=body.tags,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        if app is None:
            raise HTTPException(status_code=404, detail="chat app not found")
        return app

    @app.post("/chat_apps/{chat_app_id}/favorite", tags=["chat_apps"])
    async def favorite_chat_app_ep(chat_app_id: str, req: Request) -> dict[str, Any]:
        ok = await favorite_app(req.app.state.engine, req.state.tenant_id, req.state.user_id, chat_app_id)
        if not ok:
            raise HTTPException(status_code=404, detail="chat app not found")
        return {"chat_app_id": chat_app_id, "favorited": True}

    @app.delete("/chat_apps/{chat_app_id}/favorite", tags=["chat_apps"])
    async def unfavorite_chat_app_ep(chat_app_id: str, req: Request) -> dict[str, Any]:
        ok = await unfavorite_app(req.app.state.engine, req.state.tenant_id, req.state.user_id, chat_app_id)
        if not ok:
            raise HTTPException(status_code=404, detail="chat app not found")
        return {"chat_app_id": chat_app_id, "favorited": False}

    # ── tech-debt #18 Task 5: 应用「API 访问」密钥管理（内部 JWT，前端页签用） ──

    async def _app_exists(chat_app_id: str, req: Request) -> None:
        if await get_chat_app(req.app.state.engine, req.state.tenant_id, chat_app_id) is None:
            raise HTTPException(status_code=404, detail="chat app not found")

    @app.get("/chat_apps/{chat_app_id}/api-keys", tags=["chat_apps"])
    async def list_api_keys_ep(chat_app_id: str, req: Request) -> list[dict[str, Any]]:
        """密钥列表（name/status/created_at/last_used_at；永不返回 key_hash）。"""
        await _app_exists(chat_app_id, req)
        return await list_api_keys(req.app.state.engine, req.state.tenant_id, chat_app_id)

    @app.post("/chat_apps/{chat_app_id}/api-keys", status_code=201, tags=["chat_apps"])
    async def create_api_key_ep(chat_app_id: str, req_body: ApiKeyCreate, req: Request) -> dict[str, Any]:
        """生成密钥：明文仅此一次返回（前端一次性展示+复制），落库仅 key_hash。"""
        await _app_exists(chat_app_id, req)
        try:
            plaintext = await create_api_key(req.app.state.engine, req.state.tenant_id, chat_app_id, req_body.name)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return {"chat_app_id": chat_app_id, "name": req_body.name, "plaintext": plaintext}

    @app.post("/chat_apps/{chat_app_id}/api-keys/{api_key_id}/revoke", tags=["chat_apps"])
    async def revoke_api_key_ep(chat_app_id: str, api_key_id: str, req: Request) -> dict[str, Any]:
        """吊销（active → revoked，即时生效）。幂等：已吊销返回 revoked=false。"""
        await _app_exists(chat_app_id, req)
        ok = await revoke_api_key(req.app.state.engine, req.state.tenant_id, api_key_id)
        return {"api_key_id": api_key_id, "revoked": ok}

    @app.get("/chat_apps/{chat_app_id}/runs", tags=["chat_apps"])
    async def list_runs_ep(
        chat_app_id: str,
        limit: int = 20,
        offset: int = 0,
        req: Request = None,  # type: ignore[assignment]
    ) -> list[dict[str, Any]]:
        """运行历史（tech-debt #17 D4）：应用维度——chatflow 详情/列表页查执行轨迹。

        非 admin 按 chat_app 可见性过滤（与 search_chat_apps 同源语义，防
        「应用隐藏但轨迹可枚举」缝隙）：不可见/不存在 → 404。
        """
        app = await get_chat_app(req.app.state.engine, req.state.tenant_id, chat_app_id)
        if app is None:
            raise HTTPException(status_code=404, detail="chat app not found")
        is_admin = await is_is_admin(req.app.state.engine, req.state.tenant_id, req.state.role_id)
        if not is_admin and not await is_app_visible(
            req.app.state.engine, req.state.tenant_id, chat_app_id, req.state.role_id
        ):
            raise HTTPException(status_code=404, detail="chat app not found")
        return await list_runs(
            req.app.state.engine,
            req.state.tenant_id,
            chat_app_id,
            limit=max(1, min(100, limit)),
            offset=max(0, offset),
        )

    @app.post("/chat_apps/{chat_app_id}/chat", tags=["chat_apps"], response_model=None)
    async def chat_ep(
        chat_app_id: str, req_body: ChatRequest, req: Request
    ) -> StreamingResponse | dict[str, Any] | JSONResponse:
        """对话入口：auto = SSE 流式（现状）；flow = 声明式图执行（Chatflow F2，非流式 JSON；
        F4 human_approval 挂起 → 202）。分发逻辑与对外 /api/v1/chat-apps/{id}/chat 共用。"""
        return await _chat_dispatch(req, chat_app_id, req_body)

    @app.post("/api/v1/chat-apps/{chat_app_id}/chat", tags=["api"], response_model=None)
    async def api_chat_ep(
        chat_app_id: str, req_body: ChatRequest, req: Request
    ) -> StreamingResponse | dict[str, Any] | JSONResponse:
        """对外 API（tech-debt #18 D3/D4/D5）：Bearer app-<key> 调用已发布应用。

        - 密钥绑定 == 路径应用，否则 403（密钥即授权，D4）
        - 仅已发布（status=published）可被调用；未发布/不存在 → 404（不暴露存在性）
        - role_id 取应用创建者当前角色或空（D5）；响应语义与内部端点一致
          （auto SSE / flow JSON / human_approval 挂起 202 → conversation_id 续调恢复）
        """
        if getattr(req.state, "chat_app_id", None) != chat_app_id:
            raise HTTPException(status_code=403, detail="API key not bound to this chat app")
        app = await get_chat_app(req.app.state.engine, req.state.tenant_id, chat_app_id)
        if app is None or app.get("status") != "published":
            raise HTTPException(status_code=404, detail="chat app not found")
        req.state.role_id = await _service_role(req.app.state.engine, req.state.tenant_id, app)
        # D6: earp.api.* 审计（started → completed/failed，含耗时/状态码；flow 完成带 execution_id）
        # + last_used_at 端点完成时更新一次（防热路径写放大，D4）。
        started_at = time.monotonic()
        _api_audit(req, "earp.api.chat.started")
        try:
            response = await _chat_dispatch(req, chat_app_id, req_body, app=app)
        except HTTPException as e:
            _api_audit(
                req,
                "earp.api.chat.failed",
                status_code=e.status_code,
                elapsed_ms=_elapsed_ms(started_at),
                extra={"error": e.detail},
            )
            raise
        except Exception:
            _api_audit(req, "earp.api.chat.failed", status_code=500, elapsed_ms=_elapsed_ms(started_at))
            raise
        finally:
            await touch_api_key(req.app.state.engine, req.state.tenant_id, req.state.api_key_id)
        _status = getattr(response, "status_code", 200)
        _extra: dict[str, Any] = {}
        if isinstance(response, dict):
            if response.get("execution_id"):
                _extra = {"execution_id": response["execution_id"]}
        elif getattr(response, "body", None):
            # flow 挂起 202（JSONResponse）：execution_id 在响应体中
            try:
                body = json.loads(bytes(response.body))
                if body.get("execution_id"):
                    _extra = {"execution_id": body["execution_id"]}
            except (TypeError, ValueError):
                pass
        _api_audit(
            req,
            "earp.api.chat.completed",
            status_code=_status,
            elapsed_ms=_elapsed_ms(started_at),
            extra=_extra,
        )
        return response

    @app.post("/chat_apps/{chat_app_id}/chat/stream", tags=["chat_apps"], response_model=None)
    async def chat_stream_ep(chat_app_id: str, req_body: ChatRequest, req: Request) -> StreamingResponse:
        """应用中心：对话流式入口。auto = 现有 SSE 逐字；flow = 节点级 SSE（设计 §4.1）。

        flow 事件序列：node_start → token → node_end → (branch | human_approval | done | error)。
        挂起后用户答复恢复 → 再次调用本端点（复用 flow_runs 恢复逻辑，与 /chat 共享）。
        """
        app = await get_chat_app(req.app.state.engine, req.state.tenant_id, chat_app_id)
        if app is None:
            raise HTTPException(status_code=404, detail="chat app not found")

        if app.get("orchestration") == "flow":
            import asyncio

            from earp_server.connector import ConnectorError
            from earp_server.orchestrator.workflow_dsl import WorkflowValidationError

            queue: asyncio.Queue = asyncio.Queue()

            async def emit(ev: str, data: dict) -> None:
                await queue.put((ev, data))

            async def run_flow() -> None:
                try:
                    await flow_chat(
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
                        on_event=emit,
                    )
                except HTTPException as e:
                    # PolicyLayer 权限拒绝 403 透传 → error 事件（SSE 无 HTTP 状态码语义）
                    await emit("error", {"message": e.detail, "http_status": e.status_code})
                except (ConnectorError, ChatError, WorkflowValidationError) as e:
                    # F7 (Task 2 D4): SSE error 事件带错误分类码（与 /chat 422 一致）
                    code = getattr(e, "code", None)
                    msg = f"flow 执行失败：{e}" if not code else f"flow 执行失败[{code}]：{e}"
                    await emit("error", {"message": msg})
                except Exception:
                    logger.exception("flow chat stream failed")
                    await emit("error", {"message": "flow 执行失败，请稍后重试"})

            async def gen():
                task = asyncio.create_task(run_flow())
                try:
                    while True:
                        ev, data = await queue.get()
                        yield f"event: {ev}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                        # 终态事件后断开：done（完成）/ error（失败）/ human_approval（挂起——
                        # 前端收到后由用户回复，走新一轮 stream 恢复；若不断开前端 streaming 卡死）
                        if ev in ("done", "error", "human_approval"):
                            break
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

            return StreamingResponse(
                gen(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache, no-transform",
                    "X-Accel-Buffering": "no",
                    "Connection": "keep-alive",
                },
            )

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
    async def list_conv(
        limit: int = 50,
        offset: int = 0,
        chat_app_id: str | None = None,
        req: Request = None,  # type: ignore[assignment]
    ) -> list[dict[str, Any]]:
        """Conversation list（新增端点 Q1）：对话日志/二期应用形态数据源；
        应用中心运行页：可选 chat_app_id 过滤 + 按当前用户过滤。
        C 系列（Task 5）：非管理员按 chat_app 可见性过滤（防缝隙）。"""
        is_admin = await is_is_admin(req.app.state.engine, req.state.tenant_id, req.state.role_id)
        return await list_conversations(
            req.app.state.engine,
            req.state.tenant_id,
            limit,
            offset,
            chat_app_id=chat_app_id,
            user_id=req.state.user_id,
            role_id=req.state.role_id,
            is_admin=is_admin,
        )

    @app.get("/conversations/{conv_id}/runs", tags=["conversations"])
    async def conversation_runs_ep(conv_id: str, req: Request) -> list[dict[str, Any]]:
        """运行历史（tech-debt #17 D4）：会话维度——对话日志页按会话展开执行轨迹。

        权限与对话日志一致（C 系列防缝隙）：非 admin 按会话可见性过滤
        （归属应用不可见/会话不存在 → 404）；admin 全可见但仍 404 不存在会话。
        """
        is_admin = await is_is_admin(req.app.state.engine, req.state.tenant_id, req.state.role_id)
        if is_admin:
            if not await conversation_exists(req.app.state.engine, req.state.tenant_id, conv_id):
                raise HTTPException(status_code=404, detail="conversation not found")
        elif not await conversation_visible(req.app.state.engine, req.state.tenant_id, conv_id, req.state.role_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        return await get_conversation_runs(req.app.state.engine, req.state.tenant_id, conv_id)

    @app.post("/conversations/{conv_id}/messages", status_code=201, tags=["conversations"])
    async def add_msg(conv_id: str, req_body: MsgAdd, req: Request) -> dict[str, Any]:
        return await add_message(
            req.app.state.engine, req.state.tenant_id, conv_id, req_body.role, req_body.content, req.state.user_id
        )

    @app.get("/conversations/{conv_id}/messages", tags=["conversations"])
    async def list_msgs(conv_id: str, limit: int = 50, offset: int = 0, req: Request = None) -> list[dict[str, Any]]:  # type: ignore[assignment]
        is_admin = await is_is_admin(req.app.state.engine, req.state.tenant_id, req.state.role_id)
        return await get_messages(
            req.app.state.engine,
            req.state.tenant_id,
            conv_id,
            limit,
            offset,
            role_id=req.state.role_id,
            is_admin=is_admin,
        )

    # ── Copilot (AI 配置助手) ──
    @app.post("/copilot/assist", tags=["copilot"], response_model=None)
    async def copilot_assist_ep(req_body: CopilotAssistRequest, req: Request) -> StreamingResponse:
        """AI 配置助手 — SSE 流式响应。

        前端传入当前页面 ID + 表单状态 + 用户问题，
        后端组装上下文（页面 schema + KB 检索 + LLM）并流式返回。
        """
        from earp_server.copilot.service import copilot_assist

        async def gen():
            async for line in copilot_assist(
                req.app.state.engine,
                req.state.tenant_id,
                req_body.page_id,
                req_body.form_state,
                req_body.query,
                req_body.intent,
                llm=req.app.state.copilot_llm,
                settings=req.app.state.settings,
                rate_limiter=req.app.state.rate_limiter,
                embedding_dim=req.app.state.settings.embedding_dim,
                conversation_id=req_body.conversation_id,
                role_id=req.state.role_id,
                user_id=req.state.user_id or "user-copilot",
            ):
                yield line

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.get("/copilot/pages", tags=["copilot"])
    async def copilot_pages_ep() -> list[dict[str, Any]]:
        """返回所有已注册的 Copilot 页面列表。"""
        from earp_server.copilot.page_registry import list_pages

        return list_pages()

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
