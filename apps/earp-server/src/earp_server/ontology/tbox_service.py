"""Ontology TBox service — entity types / relation types / capability mapping.

PRD-2026-030 M1. Native-SQL style (matches knowledge/ modules), RLS via
SET LOCAL earp.tenant_id. Seeds per-tenant with ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# ── TBox seeds (ontology-layer-design §3.1/§3.2) ──────────────────────────────
SEED_ENTITY_TYPES: list[tuple[str, str, str, str, str]] = [
    # entity_type_id, name, kind, data_domain_id, description
    ("equipment", "设备", "object", "equipment_data", "生产设备/机床"),
    ("component", "部件", "object", "equipment_data", "设备关键部件（主轴/轴承/电机），一级结构不建层级"),
    ("production_line", "产线", "object", "equipment_data", "生产线"),
    ("plant", "工厂", "object", "corporate_data", "工厂/厂区"),
    ("sensor", "传感器", "object", "equipment_data", "设备监测传感器"),
    ("alarm", "报警", "object", "quality_data", "设备报警事件"),
    ("work_order", "工单", "object", "production_data", "维修/生产工单"),
    ("material", "物料", "object", "supply_chain_data", "原材料/半成品/成品"),
    ("product", "产品", "object", "production_data", "产品"),
    ("supplier", "供应商", "object", "supply_chain_data", "供应商"),
    ("customer", "客户", "object", "supply_chain_data", "客户"),
    ("employee", "员工", "object", "hr_data", "内部员工"),
    ("department", "部门", "object", "hr_data", "组织部门"),
]

SEED_RELATION_TYPES: list[tuple[str, str, str, str, str]] = [
    # relation_type_id, name, source_type(s), target_type(s), cardinality
    # 2026-08-15 决策（TBox 部件级关系缺口，方案 A）：belongs_to/supplied_by 源集合
    # 扩 component——部件属于设备（component→equipment）、部件由供应商供应
    # （component→supplier）。设计 §3.2 表格已同步。
    ("located_in", "位于", "equipment,sensor,production_line", "plant", "N:1"),
    ("belongs_to", "属于", "equipment,sensor,component", "production_line,equipment", "N:1"),
    ("manufactured_by", "由…制造", "equipment", "supplier", "N:1"),
    ("supplied_by", "由…供应", "material,component", "supplier", "N:1"),
    ("maintained_by", "由…维护", "equipment", "employee", "N:M"),
    ("responsible_for", "负责", "employee,department", "production_line,equipment,material", "N:M"),
    ("produces", "生产", "production_line,plant", "product", "1:N"),
    ("consumes", "消耗", "equipment,production_line", "material", "N:M"),
    ("caused_by", "由…引起", "alarm", "equipment,sensor,component", "N:1"),
    ("monitored_by", "被…监测", "equipment", "sensor", "1:N"),
    ("relates_to", "关联", "work_order", "equipment,material,product", "N:M"),
    ("approved_by", "由…批准", "work_order", "employee", "N:1"),
]


async def init_tenant_tbox(engine: AsyncEngine, tenant_id: str) -> None:
    """Seed the 13 entity types + 12 relation types for a tenant (idempotent)."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        for entity_type_id, name, kind, dd, desc in SEED_ENTITY_TYPES:
            await conn.execute(
                text(
                    "INSERT INTO entity_types (entity_type_id, tenant_id, name, kind, description, data_domain_id) "
                    "VALUES (:id, :tid, :name, :kind, :desc, :dd) "
                    "ON CONFLICT (entity_type_id, tenant_id) DO NOTHING"
                ),
                {"id": entity_type_id, "tid": tenant_id, "name": name, "kind": kind, "desc": desc, "dd": dd},
            )
        for relation_type_id, name, src, tgt, card in SEED_RELATION_TYPES:
            await conn.execute(
                text(
                    "INSERT INTO relation_types "
                    "(relation_type_id, tenant_id, name, source_type, target_type, cardinality) "
                    "VALUES (:id, :tid, :name, :src, :tgt, :card) "
                    "ON CONFLICT (relation_type_id, tenant_id) DO NOTHING"
                ),
                {"id": relation_type_id, "tid": tenant_id, "name": name, "src": src, "tgt": tgt, "card": card},
            )
        await conn.commit()


async def create_entity_type(
    engine: AsyncEngine,
    tenant_id: str,
    entity_type_id: str,
    name: str,
    *,
    kind: str = "object",
    description: str | None = None,
    data_domain_id: str | None = None,
    attributes: dict | None = None,
    owner: str | None = None,
) -> dict:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        existing = await conn.execute(
            text("SELECT status FROM entity_types WHERE entity_type_id = :id AND tenant_id = :tid"),
            {"id": entity_type_id, "tid": tenant_id},
        )
        row = existing.fetchone()
        if row is not None:
            # 2026-08-16：重复创建优雅拒绝（原为 500 主键冲突）。停用是软终态，
            # 不提供「再次启用」（TBox 变更需治理，tech-debt #12）。
            if row.status == "deprecated":
                raise ValueError(f"实体类型已存在且已停用: {entity_type_id}（如需启用请走治理流程）")
            raise ValueError(f"实体类型已存在: {entity_type_id}")
        await conn.execute(
            text(
                "INSERT INTO entity_types "
                "(entity_type_id, tenant_id, name, kind, description, data_domain_id, attributes, owner) "
                "VALUES (:id, :tid, :name, :kind, :desc, :dd, :attrs, :owner)"
            ),
            {
                "id": entity_type_id,
                "tid": tenant_id,
                "name": name,
                "kind": kind,
                "desc": description,
                "dd": data_domain_id,
                "attrs": __import__("json").dumps(attributes or {}),
                "owner": owner,
            },
        )
        await conn.commit()
    return {"entity_type_id": entity_type_id, "name": name, "kind": kind}


async def list_entity_types(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    data_domain_id: str | None = None,
    kind: str | None = None,
    status: str = "active",
) -> list[dict]:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        sql = "SELECT * FROM entity_types WHERE tenant_id = :tid"
        params: dict = {"tid": tenant_id}
        if status != "all":  # all = 不过滤状态（含 deprecated）
            sql += " AND status = :st"
            params["st"] = status
        if data_domain_id:
            sql += " AND data_domain_id = :dd"
            params["dd"] = data_domain_id
        if kind:
            sql += " AND kind = :kind"
            params["kind"] = kind
        sql += " ORDER BY entity_type_id"
        rows = await conn.execute(text(sql), params)
        return [dict(r._mapping) for r in rows.fetchall()]


async def deprecate_entity_type(engine: AsyncEngine, tenant_id: str, entity_type_id: str) -> dict | None:
    """Deprecate an entity type (软停用；已停用再次调用返回 None，幂等)."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text(
                "UPDATE entity_types SET status = 'deprecated', updated_at = now() "
                "WHERE entity_type_id = :id AND status = 'active' RETURNING entity_type_id, status"
            ),
            {"id": entity_type_id},
        )
        await conn.commit()
        r = result.fetchone()
        return dict(r._mapping) if r else None


async def list_relation_types(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    source_type: str | None = None,
    status: str = "active",
) -> list[dict]:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        sql = "SELECT * FROM relation_types WHERE tenant_id = :tid"
        params: dict = {"tid": tenant_id}
        if status != "all":
            sql += " AND status = :st"
            params["st"] = status
        if source_type:
            sql += " AND source_type LIKE :src"
            params["src"] = f"%{source_type}%"
        sql += " ORDER BY relation_type_id"
        rows = await conn.execute(text(sql), params)
        return [dict(r._mapping) for r in rows.fetchall()]


async def create_relation_type(
    engine: AsyncEngine,
    tenant_id: str,
    relation_type_id: str,
    name: str,
    source_type: str,
    target_type: str,
    cardinality: str,
) -> dict:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        existing = await conn.execute(
            text("SELECT status FROM relation_types WHERE relation_type_id = :id AND tenant_id = :tid"),
            {"id": relation_type_id, "tid": tenant_id},
        )
        row = existing.fetchone()
        if row is not None:
            if row.status == "deprecated":
                raise ValueError(f"关系类型已存在且已停用: {relation_type_id}（如需启用请走治理流程）")
            raise ValueError(f"关系类型已存在: {relation_type_id}")
        await conn.execute(
            text(
                "INSERT INTO relation_types "
                "(relation_type_id, tenant_id, name, source_type, target_type, cardinality) "
                "VALUES (:id, :tid, :name, :src, :tgt, :card)"
            ),
            {
                "id": relation_type_id,
                "tid": tenant_id,
                "name": name,
                "src": source_type,
                "tgt": target_type,
                "card": cardinality,
            },
        )
        await conn.commit()
    return {"relation_type_id": relation_type_id, "name": name}


async def deprecate_relation_type(engine: AsyncEngine, tenant_id: str, relation_type_id: str) -> dict | None:
    """Deprecate a relation type (软停用；已存在 facts 保留，不再允许新建该关系)."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text(
                "UPDATE relation_types SET status = 'deprecated' "
                "WHERE relation_type_id = :id AND status = 'active' "
                "RETURNING relation_type_id, status"
            ),
            {"id": relation_type_id},
        )
        await conn.commit()
        r = result.fetchone()
        return dict(r._mapping) if r else None


async def map_capability_entity(
    engine: AsyncEngine,
    tenant_id: str,
    capability_id: str,
    entity_type_id: str,
    operation: str = "read",
) -> dict:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO capability_entity_map (capability_id, entity_type_id, tenant_id, operation) "
                "VALUES (:cid, :et, :tid, :op) "
                "ON CONFLICT (capability_id, entity_type_id, tenant_id) "
                "DO UPDATE SET operation = EXCLUDED.operation"
            ),
            {"cid": capability_id, "et": entity_type_id, "tid": tenant_id, "op": operation},
        )
        await conn.commit()
    return {"capability_id": capability_id, "entity_type_id": entity_type_id, "operation": operation}


async def find_capabilities_by_entity_type(
    engine: AsyncEngine,
    tenant_id: str,
    entity_type_id: str,
) -> list[dict]:
    """Reverse lookup: capabilities that operate on an entity type (planner-spec §5.1.5)."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT c.capability_id, c.domain, c.name, c.type, m.operation "
                "FROM capability_entity_map m "
                "JOIN business_capabilities c ON c.capability_id = m.capability_id AND c.tenant_id = m.tenant_id "
                "WHERE m.tenant_id = :tid AND m.entity_type_id = :et AND m.status = 'active' "
                "ORDER BY m.operation"
            ),
            {"tid": tenant_id, "et": entity_type_id},
        )
        return [dict(r._mapping) for r in rows.fetchall()]


# ── tech-debt #12: TBox 审批流（tbox_changes 变更请求）────────────────────────


async def _get_tbox_row(engine: AsyncEngine, tenant_id: str, table: str, target_id: str) -> dict | None:
    """按 (id, tenant) 查实体/关系类型行（审批提交预检用）。table: entity_types | relation_types"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                f"SELECT * FROM {table} WHERE tenant_id = :tid AND "
                f"{'entity_type_id' if table == 'entity_types' else 'relation_type_id'} = :id"
            ),
            {"tid": tenant_id, "id": target_id},
        )
        r = rows.fetchone()
        return dict(r._mapping) if r else None


_REL_CARDINALITIES = ("1:1", "1:N", "N:1", "N:M")


async def _plan_relation_update(conn, tenant_id: str, target_id: str, payload: dict) -> dict:
    """关系类型编辑计划（设计 2026-09-04 §3；submit 预检与 approve apply 复检共用，conn 须已 SET LOCAL）。

    校验：类型存在且 active；name 非空 / cardinality 枚举；集合非空且类型 id 存在（status 任意）；
    **收窄守护**——被移除组合仍有 active 事实 → 拒绝；传入字段与现值全同 → 「数据未变更」。
    返回 {old, new, changed: [字段…]}（new 为生效后的整行值）。
    """
    row = await conn.execute(
        text("SELECT * FROM relation_types WHERE relation_type_id = :rid AND tenant_id = :tid"),
        {"rid": target_id, "tid": tenant_id},
    )
    r = row.fetchone()
    if r is None:
        raise ValueError(f"关系类型不存在: {target_id}")
    if r.status != "active":
        raise ValueError(f"关系类型已停用: {target_id}（请先提交 reactivate 恢复后再编辑）")
    old = dict(r._mapping)

    name = payload.get("name")
    if name is not None:
        name = str(name).strip()
        if not name:
            raise ValueError("关系类型名称不能为空")
    card = payload.get("cardinality")
    if card is not None and card not in _REL_CARDINALITIES:
        raise ValueError(f"非法 cardinality: {card}（可选 {'/'.join(_REL_CARDINALITIES)}）")

    def _sets(value, current: str) -> list[str]:
        if value is None:
            return [x for x in (current or "").split(",") if x]
        return [x.strip() for x in str(value).split(",") if x.strip()]

    new_src = _sets(payload.get("source_type"), old["source_type"])
    new_tgt = _sets(payload.get("target_type"), old["target_type"])
    if not new_src:
        raise ValueError("source_type 集合不能为空")
    if not new_tgt:
        raise ValueError("target_type 集合不能为空")
    all_ids = sorted(set(new_src) | set(new_tgt))
    rows = await conn.execute(
        text("SELECT entity_type_id FROM entity_types WHERE tenant_id = :tid AND entity_type_id = ANY(:ids)"),
        {"tid": tenant_id, "ids": all_ids},
    )
    known = {x.entity_type_id for x in rows.fetchall()}
    missing = [i for i in all_ids if i not in known]
    if missing:
        raise ValueError(f"源/目标类型不存在: {missing}")

    old_src = {x for x in (old["source_type"] or "").split(",") if x}
    old_tgt = {x for x in (old["target_type"] or "").split(",") if x}
    if old_src - set(new_src) or old_tgt - set(new_tgt):
        cnt = await conn.execute(
            text(
                "SELECT count(*) AS n FROM facts f "
                "JOIN entities s ON s.entity_id = f.source_entity_id "
                "JOIN entities t ON t.entity_id = f.target_entity_id "
                "WHERE f.tenant_id = :tid AND f.relation_type_id = :rid AND f.status = 'active' "
                "AND (NOT (s.entity_type_id = ANY(:srcs)) OR NOT (t.entity_type_id = ANY(:tgts)))"
            ),
            {"tid": tenant_id, "rid": target_id, "srcs": list(new_src), "tgts": list(new_tgt)},
        )
        n = int(cnt.scalar() or 0)
        if n:
            raise ValueError(
                f"收窄被拒：{n} 条 active 事实落在将被移除的组合（源或目标类型 ∉ 新集合），请先停用/清理这些事实后重试"
            )

    new = dict(old)
    changed: list[str] = []
    for field in ("name", "source_type", "target_type", "cardinality"):
        v = payload.get(field)
        if v is None:
            continue
        v = ",".join(_sets(v, old[field])) if field in ("source_type", "target_type") else str(v).strip()
        if v == old.get(field):
            continue
        new[field] = v
        changed.append(field)
    if not changed:
        raise ValueError(f"数据未变更: {target_id}")
    return {"old": old, "new": new, "changed": changed}


async def submit_change(
    engine: AsyncEngine,
    tenant_id: str,
    user_id: str,
    *,
    change_type: str,
    action: str,
    target_id: str,
    payload: dict | None = None,
) -> dict:
    """提交 TBox 变更请求（pending）。create 预检目标 id 冲突（active 拒绝；deprecated 提示走恢复）；
    update（2026-09 两线：entity_type 数据域迁移 / relation_type 编辑）预检见各 helper。"""
    if change_type not in ("entity_type", "relation_type"):
        raise ValueError(f"非法 change_type: {change_type}")
    if action not in ("create", "deprecate", "reactivate", "update"):
        raise ValueError(f"非法 action: {action}")
    payload = payload or {}

    domain_from: str | None = None
    entity_count: int | None = None

    if action == "create":
        table = "entity_types" if change_type == "entity_type" else "relation_types"
        existing = await _get_tbox_row(engine, tenant_id, table, target_id)
        if existing is not None:
            if existing["status"] == "deprecated":
                raise ValueError(f"{change_type} 已存在且已停用: {target_id}（如需恢复请提交 reactivate 请求）")
            raise ValueError(f"{change_type} 已存在: {target_id}")
        if change_type == "entity_type":
            if not payload.get("name"):
                raise ValueError("create 实体类型缺少 name")
        else:
            for k in ("name", "source_type", "target_type"):
                if not payload.get(k):
                    raise ValueError(f"create 关系类型缺少 {k}")
    elif action == "update":
        if change_type == "entity_type":
            # 数据域变更：仅实体类型；类型 active；新域≠当前域；
            # 目标域存在且 active（与 roles_service._validate_domain_access 同口径）
            existing = await _get_tbox_row(engine, tenant_id, "entity_types", target_id)
            if existing is None:
                raise ValueError(f"实体类型不存在: {target_id}")
            if existing["status"] != "active":
                raise ValueError(f"实体类型已停用: {target_id}（请先提交 reactivate 恢复后再改域）")
            new_dd = str(payload.get("data_domain_id") or "").strip()
            if not new_dd:
                raise ValueError("update 缺少 data_domain_id")
            if new_dd == existing["data_domain_id"]:
                raise ValueError(f"数据域未变更: {target_id}（当前已是 {new_dd}）")
            domain_from = existing["data_domain_id"]
            async with engine.connect() as conn:
                await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
                drow = await conn.execute(
                    text(
                        "SELECT data_domain_id FROM data_domains "
                        "WHERE tenant_id = :tid AND data_domain_id = :dd AND status = 'active'"
                    ),
                    {"tid": tenant_id, "dd": new_dd},
                )
                if drow.fetchone() is None:
                    raise ValueError(f"目标数据域不存在或未启用: {new_dd}")
                crow = await conn.execute(
                    text(
                        "SELECT count(*) AS n FROM entities WHERE tenant_id = :tid "
                        "AND entity_type_id = :et AND status IN ('active','deprecated')"
                    ),
                    {"tid": tenant_id, "et": target_id},
                )
                entity_count = int(crow.scalar() or 0)
        else:
            # 关系类型编辑（设计 2026-09-04）：源/目标集合 + 名称 + 基数；收窄守护同预检复检
            async with engine.connect() as conn:
                await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
                await _plan_relation_update(conn, tenant_id, target_id, payload)

    cid = f"tc-{uuid.uuid4().hex[:12]}"
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO tbox_changes (change_id, tenant_id, change_type, action, target_id, "
                "payload, status, requested_by) "
                "VALUES (:cid, :tid, :ct, :act, :tid2, :p, 'pending', :req)"
            ),
            {
                "cid": cid,
                "tid": tenant_id,
                "ct": change_type,
                "act": action,
                "tid2": target_id,
                "p": json.dumps(payload),
                "req": user_id,
            },
        )
        await conn.commit()
    result: dict[str, Any] = {"change_id": cid, "status": "pending"}
    if action == "update":
        result.update({"domain_from": domain_from, "entity_count": entity_count})
    return result


async def list_changes(engine: AsyncEngine, tenant_id: str, *, status: str | None = None) -> list[dict]:
    """变更请求列表（审批区；pending 优先 + 新→旧）。"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        sql = "SELECT * FROM tbox_changes WHERE tenant_id = :tid"
        params: dict = {"tid": tenant_id}
        if status:
            sql += " AND status = :st"
            params["st"] = status
        sql += " ORDER BY (status = 'pending') DESC, created_at DESC"
        rows = await conn.execute(text(sql), params)
        return [dict(r._mapping) for r in rows.fetchall()]


async def approve_change(
    engine: AsyncEngine,
    tenant_id: str,
    reviewer: str,
    change_id: str,
    *,
    role_id: str = "",
) -> dict:
    """审批通过：apply 真实变更（create/deprecate/reactivate/update）→ 请求 applied。

    tech-debt #9 审批人角色门禁：角色需 tbox.approve 权限或 is_admin；
    提交者不能审批自己（403）；apply 失败（并发冲突等）→ 抛错，请求保持 pending。
    update（数据域变更）走单连接单事务：类型域 + 名下 active/deprecated 实例域级联迁移
    （merged 不随迁）+ applied 一并提交；profile 由读时 freshness（updated_at bump）自动覆盖。
    """
    from earp_server.policy.roles_service import check_permission

    if not await check_permission(engine, tenant_id, role_id, "tbox.approve"):
        raise PermissionError("当前角色无 tbox.approve 权限，不能审批 TBox 变更")
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT * FROM tbox_changes WHERE change_id = :cid AND tenant_id = :tid"),
            {"cid": change_id, "tid": tenant_id},
        )
        r = row.fetchone()
        if r is None:
            raise ValueError(f"变更请求不存在: {change_id}")
        if r.status != "pending":
            raise ValueError(f"变更请求状态非 pending: {r.status}")
        if r.requested_by == reviewer:
            raise PermissionError("不能审批自己提交的变更")

    # apply（独立连接写类型表——RLS 自动按租户）
    if r.action == "create":
        p = r.payload
        if r.change_type == "entity_type":
            await create_entity_type(
                engine,
                tenant_id,
                r.target_id,
                p.get("name"),
                kind=p.get("kind", "object"),
                description=p.get("description"),
                data_domain_id=p.get("data_domain_id"),
                attributes=p.get("attributes"),
                owner=p.get("owner"),
            )
        else:
            await create_relation_type(
                engine,
                tenant_id,
                r.target_id,
                p.get("name"),
                p.get("source_type", ""),
                p.get("target_type", ""),
                p.get("cardinality", "N:M"),
            )
    elif r.action == "deprecate":
        if r.change_type == "entity_type":
            await deprecate_entity_type(engine, tenant_id, r.target_id)
        else:
            await deprecate_relation_type(engine, tenant_id, r.target_id)
    elif r.action == "reactivate":
        if r.change_type == "entity_type":
            await reactivate_entity_type(engine, tenant_id, r.target_id)
        else:
            await reactivate_relation_type(engine, tenant_id, r.target_id)
    elif r.action == "update":
        if r.change_type == "entity_type":
            return await _apply_domain_update(engine, tenant_id, reviewer, change_id, r)
        return await _apply_relation_update(engine, tenant_id, reviewer, change_id, r)
    else:  # 理论不可达（submit 校验）
        raise ValueError(f"非法 action: {r.action}")

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "UPDATE tbox_changes SET status = 'applied', reviewed_by = :r, reviewed_at = now() "
                "WHERE change_id = :cid AND tenant_id = :tid"
            ),
            {"r": reviewer, "cid": change_id, "tid": tenant_id},
        )
        await conn.commit()
    return {"change_id": change_id, "status": "applied"}


async def _apply_domain_update(
    engine: AsyncEngine,
    tenant_id: str,
    reviewer: str,
    change_id: str,
    r: Any,
) -> dict:
    """apply 数据域变更（update）：单事务 = 类型域 + active/deprecated 实例域级联迁移 + applied。

    设计：arch/design/2026-09-04-entity-type-data-domain-change-design.md §4.1/§4.2。
    apply 复检（类型存在&active、目标域 active）；任一失败抛错，请求保持 pending。
    merged（已吸收）实例不随迁；级联 bump updated_at → profile 读时 freshness 自动重编译。
    """
    p = r.payload if isinstance(r.payload, dict) else {}
    new_dd = str(p.get("data_domain_id") or "").strip()
    if not new_dd:
        raise ValueError("update 请求缺少 data_domain_id")
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        trow = await conn.execute(
            text("SELECT data_domain_id, status FROM entity_types WHERE entity_type_id = :et AND tenant_id = :tid"),
            {"et": r.target_id, "tid": tenant_id},
        )
        t = trow.fetchone()
        if t is None:
            raise ValueError(f"实体类型不存在: {r.target_id}")
        if t.status != "active":
            raise ValueError(f"实体类型已停用: {r.target_id}")
        domain_from = t.data_domain_id
        drow = await conn.execute(
            text(
                "SELECT data_domain_id FROM data_domains "
                "WHERE tenant_id = :tid AND data_domain_id = :dd AND status = 'active'"
            ),
            {"tid": tenant_id, "dd": new_dd},
        )
        if drow.fetchone() is None:
            raise ValueError(f"目标数据域不存在或未启用: {new_dd}")

        await conn.execute(
            text(
                "UPDATE entity_types SET data_domain_id = :dd, updated_at = now() "
                "WHERE entity_type_id = :et AND tenant_id = :tid"
            ),
            {"dd": new_dd, "et": r.target_id, "tid": tenant_id},
        )
        moved = await conn.execute(
            text(
                "UPDATE entities SET data_domain_id = :dd, updated_at = now() "
                "WHERE entity_type_id = :et AND tenant_id = :tid "
                "AND status IN ('active','deprecated')"
            ),
            {"dd": new_dd, "et": r.target_id, "tid": tenant_id},
        )
        await conn.execute(
            text(
                "UPDATE tbox_changes SET status = 'applied', reviewed_by = :r, reviewed_at = now() "
                "WHERE change_id = :cid AND tenant_id = :tid"
            ),
            {"r": reviewer, "cid": change_id, "tid": tenant_id},
        )
        await conn.commit()
    return {
        "change_id": change_id,
        "status": "applied",
        "domain_from": domain_from,
        "domain_to": new_dd,
        "entity_count": int(moved.rowcount or 0),
    }


async def _apply_relation_update(
    engine: AsyncEngine,
    tenant_id: str,
    reviewer: str,
    change_id: str,
    r: Any,
) -> dict:
    """apply 关系类型编辑（设计 2026-09-04 §4）：单事务 = UPDATE relation_types（传入字段）
    + applied；收窄守护与 submit 同源（_plan_relation_update 复检，防并发窗口）。
    存量 facts 天然保留（无实例级联）；审计留痕靠 tbox_changes 行 + approved 事件。
    """
    p = r.payload if isinstance(r.payload, dict) else {}
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        plan = await _plan_relation_update(conn, tenant_id, r.target_id, p)
        if plan["changed"]:
            sets: list[str] = []
            params: dict[str, Any] = {"tid": tenant_id, "rid": r.target_id}
            for f in plan["changed"]:
                sets.append(f"{f} = :{f}")
                params[f] = plan["new"][f]
            await conn.execute(
                text(f"UPDATE relation_types SET {', '.join(sets)} WHERE relation_type_id = :rid AND tenant_id = :tid"),
                params,
            )
        await conn.execute(
            text(
                "UPDATE tbox_changes SET status = 'applied', reviewed_by = :r, reviewed_at = now() "
                "WHERE change_id = :cid AND tenant_id = :tid"
            ),
            {"r": reviewer, "cid": change_id, "tid": tenant_id},
        )
        await conn.commit()
    return {"change_id": change_id, "status": "applied", "fields_changed": plan["changed"]}


async def reject_change(
    engine: AsyncEngine,
    tenant_id: str,
    reviewer: str,
    change_id: str,
    reason: str,
    *,
    role_id: str = "",
) -> dict:
    """拒绝变更请求（pending → rejected + 原因）。审批人角色门禁同 approve。"""
    from earp_server.policy.roles_service import check_permission

    if not await check_permission(engine, tenant_id, role_id, "tbox.approve"):
        raise PermissionError("当前角色无 tbox.approve 权限，不能审批 TBox 变更")
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text(
                "UPDATE tbox_changes SET status = 'rejected', reviewed_by = :r, "
                "review_reason = :reason, reviewed_at = now() "
                "WHERE change_id = :cid AND tenant_id = :tid AND status = 'pending' "
                "RETURNING change_id, status"
            ),
            {"r": reviewer, "reason": reason, "cid": change_id, "tid": tenant_id},
        )
        await conn.commit()
        r = result.fetchone()
        if r is None:
            raise ValueError(f"变更请求不存在或非 pending: {change_id}")
        return dict(r._mapping)


async def reactivate_entity_type(engine: AsyncEngine, tenant_id: str, entity_type_id: str) -> dict | None:
    """恢复实体类型（deprecated → active；幂等——非 deprecated 不生效返回 None）。"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text(
                "UPDATE entity_types SET status = 'active', updated_at = now() "
                "WHERE entity_type_id = :id AND tenant_id = :tid AND status = 'deprecated' "
                "RETURNING entity_type_id, status"
            ),
            {"id": entity_type_id, "tid": tenant_id},
        )
        await conn.commit()
        r = result.fetchone()
        return dict(r._mapping) if r else None


async def reactivate_relation_type(engine: AsyncEngine, tenant_id: str, relation_type_id: str) -> dict | None:
    """恢复关系类型（deprecated → active；幂等）。"""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text(
                "UPDATE relation_types SET status = 'active' "
                "WHERE relation_type_id = :id AND tenant_id = :tid AND status = 'deprecated' "
                "RETURNING relation_type_id, status"
            ),
            {"id": relation_type_id, "tid": tenant_id},
        )
        await conn.commit()
        r = result.fetchone()
        return dict(r._mapping) if r else None
