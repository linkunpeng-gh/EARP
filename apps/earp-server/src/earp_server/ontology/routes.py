"""Ontology API routes (PRD-2026-030 M1) — TBox/ABox CRUD + lookup + profile."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from earp_server.ontology import abox_service, import_service, tbox_service

router = APIRouter(prefix="/v1/ontology", tags=["ontology"])


class EntityTypeIn(BaseModel):
    entity_type_id: str
    name: str
    kind: str = "object"
    description: str | None = None
    data_domain_id: str | None = None
    attributes: dict = {}
    owner: str | None = None


class RelationTypeIn(BaseModel):
    relation_type_id: str
    name: str
    source_type: str
    target_type: str
    cardinality: str


class CapabilityEntityIn(BaseModel):
    entity_type_id: str
    operation: str = "read"


class EntityIn(BaseModel):
    entity_type_id: str
    name: str
    entity_id: str | None = None
    business_code: str | None = None
    attributes: dict = {}
    source_mode: str = "extracted"
    source_ref: str | None = None
    data_domain_id: str | None = None


class FactIn(BaseModel):
    source_entity_id: str
    relation_type_id: str
    target_entity_id: str
    confidence: float = 1.0
    source_ref: str | None = None


# ── TBox ──
async def _ensure_tbox(req: Request) -> None:
    """Lazy per-tenant TBox seed (PRD-2026-030): first access initializes seeds."""
    engine = req.app.state.engine
    tid = req.state.tenant_id
    existing = await tbox_service.list_entity_types(engine, tid)
    if not existing:
        await tbox_service.init_tenant_tbox(engine, tid)


@router.get("/entity-types")
async def list_entity_types(
    req: Request,
    data_domain_id: str | None = None,
    kind: str | None = None,
    status: str = "active",
) -> list[dict]:
    await _ensure_tbox(req)
    return await tbox_service.list_entity_types(
        req.app.state.engine, req.state.tenant_id,
        data_domain_id=data_domain_id, kind=kind, status=status,
    )


@router.post("/entity-types", status_code=201)
async def create_entity_type(req_body: EntityTypeIn, req: Request) -> dict:
    try:
        return await tbox_service.create_entity_type(
            req.app.state.engine,
            req.state.tenant_id,
            req_body.entity_type_id,
            req_body.name,
            kind=req_body.kind,
            description=req_body.description,
            data_domain_id=req_body.data_domain_id,
            attributes=req_body.attributes,
            owner=req_body.owner,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post("/entity-types/{entity_type_id}/deprecate")
async def deprecate_entity_type(entity_type_id: str, req: Request) -> dict:
    updated = await tbox_service.deprecate_entity_type(req.app.state.engine, req.state.tenant_id, entity_type_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Entity type not found")
    return updated


@router.get("/relation-types")
async def list_relation_types(
    req: Request,
    source_type: str | None = None,
    status: str = "active",
) -> list[dict]:
    return await tbox_service.list_relation_types(
        req.app.state.engine, req.state.tenant_id, source_type=source_type, status=status,
    )


@router.post("/relation-types", status_code=201)
async def create_relation_type(req_body: RelationTypeIn, req: Request) -> dict:
    try:
        return await tbox_service.create_relation_type(
            req.app.state.engine,
            req.state.tenant_id,
            req_body.relation_type_id,
            req_body.name,
            req_body.source_type,
            req_body.target_type,
            req_body.cardinality,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.post("/relation-types/{relation_type_id}/deprecate")
async def deprecate_relation_type(relation_type_id: str, req: Request) -> dict:
    """软停用关系类型（已存在 facts 保留，不再允许新建该关系）。"""
    rel = await tbox_service.deprecate_relation_type(req.app.state.engine, req.state.tenant_id, relation_type_id)
    if rel is None:
        raise HTTPException(status_code=404, detail="Relation type not found or already deprecated")
    return rel


@router.post("/capabilities/{capability_id}/entities", status_code=201)
async def map_capability_entity(capability_id: str, req_body: CapabilityEntityIn, req: Request) -> dict:
    return await tbox_service.map_capability_entity(
        req.app.state.engine, req.state.tenant_id, capability_id, req_body.entity_type_id, req_body.operation
    )


@router.get("/capabilities/by-entity-type/{entity_type_id}")
async def capabilities_by_entity_type(entity_type_id: str, req: Request) -> list[dict]:
    """Reverse lookup for Resolution Engine candidate narrowing (planner-spec §5.1.5)."""
    return await tbox_service.find_capabilities_by_entity_type(
        req.app.state.engine, req.state.tenant_id, entity_type_id
    )


# ── ABox ──
@router.post("/entities", status_code=201)
async def upsert_entity(req_body: EntityIn, req: Request) -> dict:
    return await abox_service.upsert_entity(
        req.app.state.engine,
        req.state.tenant_id,
        req_body.entity_type_id,
        req_body.name,
        entity_id=req_body.entity_id,
        business_code=req_body.business_code,
        attributes=req_body.attributes,
        source_mode=req_body.source_mode,
        source_ref=req_body.source_ref,
        data_domain_id=req_body.data_domain_id,
    )


@router.get("/entities/lookup")
async def lookup_entities(
    req: Request,
    q: str,
    entity_type: str | None = None,
    top_k: int = 5,
) -> list[dict]:
    return await abox_service.lookup_entities(
        req.app.state.engine,
        req.state.tenant_id,
        q,
        entity_type_ids=[entity_type] if entity_type else None,
        top_k=top_k,
    )


@router.get("/entities")
async def list_entities(
    req: Request,
    entity_type: str | None = None,
    data_domain_id: str | None = None,
    status: str = "active",
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
) -> dict:
    """实体分页列表（M4 admin 实体管理页）。q 按名称/业务编码搜索。"""
    rows, total = await abox_service.list_entities(
        req.app.state.engine,
        req.state.tenant_id,
        entity_type_ids=[entity_type] if entity_type else None,
        data_domain_ids=[data_domain_id] if data_domain_id else None,
        status=status,
        page=page,
        page_size=page_size,
        q=q,
    )
    return {"items": rows, "total": total, "page": page, "page_size": page_size}


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str, req: Request) -> dict:
    ent = await abox_service.get_entity(req.app.state.engine, req.state.tenant_id, entity_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return ent


@router.post("/entities/{entity_id}/deprecate")
async def deprecate_entity(entity_id: str, req: Request) -> dict:
    """软停用实体（status→deprecated，实例纠错留痕，facts 保留）。"""
    ent = await abox_service.deprecate_entity(req.app.state.engine, req.state.tenant_id, entity_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Entity not found or already deprecated")
    return ent


@router.get("/entities/{entity_id}/profile")
async def get_profile(entity_id: str, req: Request) -> dict:
    profile = await abox_service.get_entity_profile(req.app.state.engine, req.state.tenant_id, entity_id)
    if profile is None:
        # auto-compile on first access (Compiled Truth, PRD-2026-030)
        profile = await abox_service.compile_profile(req.app.state.engine, req.state.tenant_id, entity_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return profile


@router.post("/entities/{entity_id}/facts", status_code=201)
async def add_fact(entity_id: str, req_body: FactIn, req: Request) -> dict:
    return await abox_service.add_fact(
        req.app.state.engine,
        req.state.tenant_id,
        req_body.source_entity_id,
        req_body.relation_type_id,
        req_body.target_entity_id,
        confidence=req_body.confidence,
        source_ref=req_body.source_ref,
    )


@router.post("/facts/{fact_id}/revoke")
async def revoke_fact(fact_id: str, req: Request) -> dict:
    revoked = await abox_service.revoke_fact(req.app.state.engine, req.state.tenant_id, fact_id)
    if revoked is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return revoked


@router.get("/entities/{entity_id}/graph")
async def graph_query(
    entity_id: str,
    req: Request,
    max_hops: int = 3,
    direction: str = "forward",
) -> list[dict]:
    if direction not in ("forward", "backward"):
        raise HTTPException(status_code=400, detail="direction 必须是 forward 或 backward")
    return await abox_service.graph_query(
        req.app.state.engine, req.state.tenant_id, entity_id, max_hops, direction=direction
    )


@router.get("/import/templates")
async def import_templates() -> dict:
    """实体/事实导入模板下载（CSV，含说明头 + 示例行）。"""
    return {
        "entities_csv": import_service.ENTITIES_TEMPLATE,
        "facts_csv": import_service.FACTS_TEMPLATE,
    }


@router.post("/import")
async def import_abox_endpoint(
    req: Request,
    entities_file: UploadFile | None = File(None),
    facts_file: UploadFile | None = File(None),
    dry_run: bool = Form(True),
) -> dict:
    """批量导入实体/事实（CSV）。dry_run=true（默认）只校验不写库，返回逐行错误。"""

    def _read(f: UploadFile | None) -> str | None:
        if f is None:
            return None
        data = f.file.read()
        if len(data) > import_service._MAX_CSV_BYTES:
            raise HTTPException(status_code=400, detail=f"{f.filename} 超过 2MB 限制")
        return data.decode("utf-8-sig")

    entities_csv = _read(entities_file)
    facts_csv = _read(facts_file)
    if not entities_csv and not facts_csv:
        raise HTTPException(status_code=400, detail="至少上传 entities.csv 或 facts.csv 之一")
    return await import_service.import_abox(
        req.app.state.engine,
        req.state.tenant_id,
        entities_csv,
        facts_csv,
        dry_run=dry_run,
    )


class UnderstandingDebugIn(BaseModel):
    query: str
    context: dict | None = None  # {conversation_id?, last_entities?: [], last_intent?}
    threshold: float | None = None  # 覆盖默认 0.7（评估/调参用，D5）


@router.post("/understanding/plan-debug")
async def understanding_plan_debug(req_body: UnderstandingDebugIn, req: Request) -> dict:
    """完整可解释链调试（Phase C Task 6，QU 设计 §15）：

    QU（StructuredQuery + 命中明细 + derive_needs + LLM 升级）→ select_plan
    （策略名 + 回落原因）→ 策略执行（PlanResult：evidence/citations/trace）。
    读端点、无写库、无迁移；Plan 不落库（QP-12）。
    """
    from earp_server.ontology.planning import execute_plan
    from earp_server.ontology.understanding import (
        build_structured_query,
        derive_needs,
        understand,
        upgrade_with_llm,
    )

    engine = req.app.state.engine
    tid = req.state.tenant_id
    await _ensure_tbox(req)
    result = await understand(engine, tid, req_body.query, context=req_body.context)
    result = await upgrade_with_llm(
        engine,
        tid,
        req_body.query,
        result,
        settings=req.app.state.settings,
        threshold=req_body.threshold if req_body.threshold is not None else 0.7,
    )
    sq = build_structured_query(result)
    sel, plan = await execute_plan(
        engine, tid, req.state.role_id, req_body.query, sq,
        settings=req.app.state.settings, context=req_body.context,
    )
    return {
        "query": req_body.query,
        "structured_query": sq.model_dump(mode="json"),
        "rule_fields": {f: ("hit" if v else "miss") for f, v in result.field_hits.items()},
        "field_reasons": result.field_reasons,
        "relevant_fields": sorted(result.relevant_fields),
        "derive_needs": derive_needs(sq),
        "llm_upgraded": result.llm_upgraded,
        "select_plan": {"plan_name": sel.plan_name, "fallback_reason": sel.fallback_reason},
        "plan_result": plan.model_dump(mode="json"),
    }


@router.post("/understanding/debug")
async def understanding_debug(req_body: UnderstandingDebugIn, req: Request) -> dict:
    """Query Understanding 调试（Phase B Task 9，QU 设计 §15 可解释模式）。

    输入 query + 可选会话上下文 → StructuredQuery（含各字段命中明细 + confidence
    分项）+ derive_needs() 结果 + 是否 LLM 升级 + relation 候选溯源。
    读端点、无写库、无迁移；复用 route_debug「分层可解释」展示模式。
    """
    from earp_server.ontology.understanding import (
        build_structured_query,
        derive_needs,
        understand,
        upgrade_with_llm,
    )

    engine = req.app.state.engine
    tid = req.state.tenant_id
    await _ensure_tbox(req)  # relation 候选依赖 TBox seed
    result = await understand(engine, tid, req_body.query, context=req_body.context)
    result = await upgrade_with_llm(
        engine,
        tid,
        req_body.query,
        result,
        settings=req.app.state.settings,
        threshold=req_body.threshold if req_body.threshold is not None else 0.7,
    )
    sq = build_structured_query(result)
    return {
        "structured_query": sq.model_dump(mode="json"),
        "rule_fields": {f: ("hit" if v else "miss") for f, v in result.field_hits.items()},
        "field_reasons": result.field_reasons,
        "relevant_fields": sorted(result.relevant_fields),
        "derive_needs": derive_needs(sq),
        "llm_upgraded": result.llm_upgraded,
        "relation_candidates_used": result.relation_candidates,
        "confidence": result.confidence,
    }


@router.get("/search")
async def knowledge_search_endpoint(
    req: Request,
    q: str,
    top_k: int = 5,
    data_domain_id: str | None = None,
) -> list[dict]:
    """Three-layer retrieval (PRD-2026-030 M2): profile + graph + vector, RRF-fused."""
    from earp_server.knowledge.embedding_service import embed_query
    from earp_server.ontology.search import knowledge_search

    try:
        emb = await embed_query(q)
    except Exception:
        emb = None  # vector layer degrades gracefully
    return await knowledge_search(
        req.app.state.engine,
        req.state.tenant_id,
        q,
        embedding=emb,
        role_id=req.state.role_id,
        data_domain_ids=[data_domain_id] if data_domain_id else None,
        top_k=top_k,
        embedding_dim=req.app.state.settings.embedding_dim,
    )
