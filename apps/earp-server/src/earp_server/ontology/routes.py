"""Ontology API routes (PRD-2026-030 M1) — TBox/ABox CRUD + lookup + profile."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from earp_server.ontology import abox_service, tbox_service

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
) -> list[dict]:
    await _ensure_tbox(req)
    return await tbox_service.list_entity_types(
        req.app.state.engine, req.state.tenant_id, data_domain_id=data_domain_id, kind=kind
    )


@router.post("/entity-types", status_code=201)
async def create_entity_type(req_body: EntityTypeIn, req: Request) -> dict:
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


@router.post("/entity-types/{entity_type_id}/deprecate")
async def deprecate_entity_type(entity_type_id: str, req: Request) -> dict:
    updated = await tbox_service.deprecate_entity_type(req.app.state.engine, req.state.tenant_id, entity_type_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Entity type not found")
    return updated


@router.get("/relation-types")
async def list_relation_types(req: Request, source_type: str | None = None) -> list[dict]:
    return await tbox_service.list_relation_types(req.app.state.engine, req.state.tenant_id, source_type=source_type)


@router.post("/relation-types", status_code=201)
async def create_relation_type(req_body: RelationTypeIn, req: Request) -> dict:
    return await tbox_service.create_relation_type(
        req.app.state.engine,
        req.state.tenant_id,
        req_body.relation_type_id,
        req_body.name,
        req_body.source_type,
        req_body.target_type,
        req_body.cardinality,
    )


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


@router.get("/entities/{entity_id}")
async def get_entity(entity_id: str, req: Request) -> dict:
    ent = await abox_service.get_entity(req.app.state.engine, req.state.tenant_id, entity_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Entity not found")
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
async def graph_query(entity_id: str, req: Request, max_hops: int = 3) -> list[dict]:
    return await abox_service.graph_query(req.app.state.engine, req.state.tenant_id, entity_id, max_hops)


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
