"""Ontology API routes (PRD-2026-030 M1) — TBox/ABox CRUD + lookup + profile."""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from earp_server.ontology import (
    abox_service,
    connector_service,
    data_adapter,
    import_service,
    tbox_service,
)
from earp_server.policy import roles_service

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
        req.app.state.engine,
        req.state.tenant_id,
        data_domain_id=data_domain_id,
        kind=kind,
        status=status,
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
        req.app.state.engine,
        req.state.tenant_id,
        source_type=source_type,
        status=status,
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


# ── M3 中台 importer：connector 管理（A1）─────────────────────────────────────


async def _require_admin(req: Request) -> None:
    """管理端门禁（2026-08-18 越权修复先例）：connector 配置含连接凭据，写操作仅 Admin。"""
    if not await roles_service.is_admin_role(req.app.state.engine, req.state.tenant_id, req.state.role_id):
        raise HTTPException(status_code=403, detail="仅 Admin 角色可管理 connector 配置")


class ConnectorIn(BaseModel):
    connector_id: str | None = None  # 缺省自动生成 cn-xxxx
    adapter_type: str
    config: dict = {}  # REST: {base_url, auth_type, username, password, token, headers, timeout_seconds}
    #                # DB:   {conn_url, table, columns, where, limit}
    status: str = "active"


class ConnectorUpdate(BaseModel):
    config: dict | None = None
    status: str | None = None


class DataSourceIn(BaseModel):
    connector_id: str
    entity_type_id: str
    source_mode: str  # virtual | synced
    field_mapping: dict  # {name_field, business_code_field, attr_fields{}, relations[]}
    incremental: dict | None = None  # {enabled, since_field, page_size}


@router.post("/connectors", status_code=201, dependencies=[Depends(_require_admin)])
async def create_connector_endpoint(body: ConnectorIn, req: Request) -> dict:
    """注册 connector（中台连接配置，加密落库）。配置不返回明文。"""
    try:
        out = await connector_service.create_connector(
            req.app.state.engine,
            req.state.tenant_id,
            connector_id=body.connector_id,
            adapter_type=body.adapter_type,
            config=body.config,
            status=body.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if out is None:
        raise HTTPException(status_code=409, detail="connector_id 已存在")
    return out


@router.get("/connectors")
async def list_connectors_endpoint(req: Request) -> dict:
    """connector 列表（脱敏，不含配置明文）。只读开放（不泄露凭据）。"""
    rows = await connector_service.list_connectors(req.app.state.engine, req.state.tenant_id)
    return {"items": rows, "total": len(rows)}


@router.patch("/connectors/{connector_id}", dependencies=[Depends(_require_admin)])
async def update_connector_endpoint(connector_id: str, body: ConnectorUpdate, req: Request) -> dict:
    """更新 connector 配置（重加密）/ 状态。"""
    out = await connector_service.update_connector(
        req.app.state.engine,
        req.state.tenant_id,
        connector_id,
        config=body.config,
        status=body.status,
    )
    if out is None:
        raise HTTPException(status_code=404, detail="connector 不存在")
    return out


@router.delete("/connectors/{connector_id}", dependencies=[Depends(_require_admin)])
async def delete_connector_endpoint(connector_id: str, req: Request) -> dict:
    """删除 connector。被数据源（import_rules）引用 → 409。"""
    ok = await connector_service.delete_connector(req.app.state.engine, req.state.tenant_id, connector_id)
    if not ok:
        # 区分 404 与 409：再查一次存在性
        existing = await connector_service.get_connector(req.app.state.engine, req.state.tenant_id, connector_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="connector 不存在")
        raise HTTPException(status_code=409, detail="connector 被数据源引用，无法删除（可停用）")
    return {"deleted": connector_id}


# ── M3 中台 importer：数据源注册（B1）─────────────────────────────────────────


@router.post("/import/connector", status_code=201, dependencies=[Depends(_require_admin)])
async def import_connector_endpoint(body: DataSourceIn, req: Request) -> dict:
    """中台数据源注册（PRD §1 #8）：virtual 建元数据 / synced 同步副本。
    field_mapping 落库（import_rules），synced 注册后立即入队同步（B2）。
    """
    try:
        out = await import_service.register_data_source(
            req.app.state.engine,
            req.state.tenant_id,
            connector_id=body.connector_id,
            entity_type_id=body.entity_type_id,
            source_mode=body.source_mode,
            field_mapping=body.field_mapping,
            incremental=body.incremental,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if out is None:
        raise HTTPException(status_code=409, detail="同 connector+entity_type+source_mode 的数据源已存在")
    # synced → 立即入队同步（B2；enqueue 失败容忍——注册本身已成功）
    if body.source_mode == "synced":
        out["job_status"] = await _enqueue_sync(req, out["data_source_id"])
    return out


async def _enqueue_sync(req: Request, data_source_id: str) -> str:
    """入队同步任务（B2）。queue 不可用/入队失败 → 记录并返回状态，不抛（注册已成功）。"""
    queue = getattr(req.app.state, "queue", None)
    if queue is None:
        return "enqueue_failed"
    try:
        await queue.enqueue(
            "ontology.sync_data_source",
            {"tenant_id": req.state.tenant_id, "data_source_id": data_source_id},
        )
        return "queued"
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("enqueue sync failed: %s", data_source_id)
        return "enqueue_failed"


@router.get("/data-sources")
async def list_data_sources_endpoint(req: Request) -> dict:
    """数据源列表（含 last_synced_at/last_sync_status）。"""
    rows = await import_service.list_data_sources(req.app.state.engine, req.state.tenant_id)
    return {"items": rows, "total": len(rows)}


@router.get("/data-sources/{data_source_id}")
async def get_data_source_endpoint(data_source_id: str, req: Request) -> dict:
    out = await import_service.get_data_source(req.app.state.engine, req.state.tenant_id, data_source_id)
    if out is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return out


@router.post("/data-sources/{data_source_id}/sync", dependencies=[Depends(_require_admin)])
async def sync_data_source_endpoint(data_source_id: str, req: Request) -> dict:
    """触发同步（入队，B2）。running 中且心跳新鲜 → 409；卡死（TTL 超时）→ 标 interrupted 再开始。"""
    ds = await import_service.get_data_source(req.app.state.engine, req.state.tenant_id, data_source_id)
    if ds is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    if ds["last_sync_status"] == "running":
        from earp_server.ontology import sync_jobs

        recovered = await sync_jobs.recover_interrupted_sync(
            req.app.state.engine,
            req.state.tenant_id,
            data_source_id,
            ttl_seconds=req.app.state.settings.sync_run_ttl,
        )
        if not recovered:
            raise HTTPException(status_code=409, detail="同步进行中（心跳新鲜），请稍后重试")
    status = await _enqueue_sync(req, data_source_id)
    return {"data_source_id": data_source_id, "job_status": status}


# ── M3 中台 importer：virtual 实时取数（C1）────────────────────────────────────


@router.get("/entities/{entity_id}/live")
async def entity_live_value_endpoint(entity_id: str, req: Request) -> dict:
    """virtual metric 实体实时取数（US-09 / AC-13）：经 connector 配置 + adapter 实时取。
    virtual 实体行经实体管理创建（source_mode='virtual'，source_ref=connector_id）；
    取数失败 → 503（不假造值）。
    """
    engine, tid = req.app.state.engine, req.state.tenant_id
    ent = await abox_service.get_entity(engine, tid, entity_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="实体不存在")
    # B 修复（review）：角色域门禁——实体 data_domain_id 不在角色允许域 → 404
    # （不暴露实体存在性，对齐单实体访问语义；admin/全权限不过滤；角色缺失/空授权 fail-closed）
    from earp_server.knowledge.search_service import _role_scope_domains

    allowed = await _role_scope_domains(engine, tid, req.state.role_id)
    if allowed is not None and ent.get("data_domain_id") not in allowed:
        raise HTTPException(status_code=404, detail="实体不存在")
    if ent.get("source_mode") != "virtual":
        raise HTTPException(status_code=400, detail="仅 virtual 实体支持实时取数")
    types = await tbox_service.list_entity_types(engine, tid)
    et = next((t for t in types if t["entity_type_id"] == ent.get("entity_type_id")), {})
    if et.get("kind") != "metric":
        raise HTTPException(status_code=400, detail="仅 metric 类型 virtual 实体支持实时取数（G1）")
    cid = ent.get("source_ref")
    if not cid:
        raise HTTPException(status_code=400, detail="virtual 实体未关联 connector（source_ref 缺失）")
    cfg = await connector_service.decrypt_config(engine, tid, cid)
    if not cfg:
        raise HTTPException(status_code=503, detail="connector 配置不可用")
    try:
        rows = await data_adapter.fetch(cfg, {"business_code": ent.get("business_code")})
    except data_adapter.ConnectorFetchError as e:
        raise HTTPException(status_code=503, detail=f"实时取数失败: {e}") from e
    from datetime import datetime

    return {
        "entity_id": entity_id,
        "business_code": ent.get("business_code"),
        "data": rows[0] if rows else None,
        "fetched_at": datetime.now(UTC).isoformat(),
        "connector_id": cid,
    }


# ── M3 Enrichment 手动触发（D1，调试/测试用）──────────────────────────────────


@router.post("/enrichment/run", dependencies=[Depends(_require_admin)])
async def enrichment_run_endpoint(req: Request) -> dict:
    """手动触发 enrichment 全流程（④③①②）。夜间由 scheduler 循环自动执行（D2）。"""
    from earp_server.ontology import enrichment

    return await enrichment.enrichment_run(req.app.state.engine, req.state.tenant_id)


# ── tech-debt #12: TBox 审批流（tbox_changes 变更请求）───────────────────────


class TboxChangeIn(BaseModel):
    change_type: str  # entity_type | relation_type
    action: str  # create | deprecate | reactivate
    target_id: str
    payload: dict = {}


class TboxRejectIn(BaseModel):
    reason: str


def _audit_tbox(bus, event_type: str, tenant_id: str, user_id: str, target_id: str, extra: dict | None = None) -> None:
    """TBox 变更审计（对齐 chat_app_service._audit 模式；bus 为空静默跳过）。"""
    if bus is None:
        return
    from earp_server.infra.eventbus import CloudEvent

    bus.publish(
        CloudEvent(
            type=event_type,
            source="earp-server/ontology",
            tenant_id=tenant_id,
            data={
                "entity_type": "tbox",
                "entity_id": target_id,
                "user_id": user_id,
                **(extra or {}),
            },
        )
    )


@router.post("/tbox/changes", status_code=201)
async def submit_tbox_change(req_body: TboxChangeIn, req: Request) -> dict:
    """提交 TBox 变更请求（pending）——新增/停用/恢复均走审批（D2）。"""
    try:
        change = await tbox_service.submit_change(
            req.app.state.engine,
            req.state.tenant_id,
            req.state.user_id,
            change_type=req_body.change_type,
            action=req_body.action,
            target_id=req_body.target_id,
            payload=req_body.payload,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    _audit_tbox(
        req.app.state.eventbus,
        "earp.tbox.change.submitted",
        req.state.tenant_id,
        req.state.user_id,
        req_body.target_id,
        {"change_id": change["change_id"], "change_type": req_body.change_type, "action": req_body.action},
    )
    return change


@router.get("/tbox/changes")
async def list_tbox_changes(req: Request, status: str | None = None) -> list[dict]:
    """变更请求列表；每项附审批能力（tech-debt #9/#12，前端据此渲染操作列）：
    can_approve（有门禁权限且非自己提交——提交者不能自审，与 approve 403 语义一致）、
    can_reject（门禁权限；提交者可拒绝/撤回自己的请求）、own（是否自己提交）。
    不向客户端泄露角色权限明细。"""
    from earp_server.policy.roles_service import check_permission

    engine = req.app.state.engine
    tid = req.state.tenant_id
    changes = await tbox_service.list_changes(engine, tid, status=status)
    gate = await check_permission(engine, tid, req.state.role_id, "tbox.approve")
    for c in changes:
        own = c["requested_by"] == req.state.user_id
        c["own"] = own
        c["can_approve"] = gate and not own
        c["can_reject"] = gate
    return changes


@router.post("/tbox/changes/{change_id}/approve")
async def approve_tbox_change(change_id: str, req: Request) -> dict:
    """审批通过（审批人角色门禁：tbox.approve 或 admin；提交者不能审自己）。"""
    try:
        result = await tbox_service.approve_change(
            req.app.state.engine,
            req.state.tenant_id,
            req.state.user_id,
            change_id,
            role_id=req.state.role_id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    _audit_tbox(
        req.app.state.eventbus,
        "earp.tbox.change.approved",
        req.state.tenant_id,
        req.state.user_id,
        change_id,
        {
            "status": result["status"],
            "domain_from": result.get("domain_from"),
            "domain_to": result.get("domain_to"),
            "entity_count": result.get("entity_count"),
            "fields_changed": result.get("fields_changed"),
        },
    )
    return result


@router.post("/tbox/changes/{change_id}/reject")
async def reject_tbox_change(change_id: str, req_body: TboxRejectIn, req: Request) -> dict:
    try:
        result = await tbox_service.reject_change(
            req.app.state.engine,
            req.state.tenant_id,
            req.state.user_id,
            change_id,
            req_body.reason,
            role_id=req.state.role_id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    _audit_tbox(
        req.app.state.eventbus,
        "earp.tbox.change.rejected",
        req.state.tenant_id,
        req.state.user_id,
        change_id,
        {"reason": req_body.reason},
    )
    return result


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
        engine,
        tid,
        req.state.role_id,
        req_body.query,
        sq,
        settings=req.app.state.settings,
        context=req_body.context,
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
