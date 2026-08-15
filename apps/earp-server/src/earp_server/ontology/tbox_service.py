"""Ontology TBox service — entity types / relation types / capability mapping.

PRD-2026-030 M1. Native-SQL style (matches knowledge/ modules), RLS via
SET LOCAL earp.tenant_id. Seeds per-tenant with ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# ── TBox seeds (ontology-layer-design §3.1/§3.2) ──────────────────────────────
SEED_ENTITY_TYPES: list[dict] = [
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

SEED_RELATION_TYPES: list[dict] = [
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
        sql = "SELECT * FROM entity_types WHERE tenant_id = :tid AND status = :st"
        params: dict = {"tid": tenant_id, "st": status}
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
    """Deprecate an entity type (TBox change requires approval — audit on caller side)."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text(
                "UPDATE entity_types SET status = 'deprecated', updated_at = now() "
                "WHERE entity_type_id = :id RETURNING entity_type_id, status"
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
        sql = "SELECT * FROM relation_types WHERE tenant_id = :tid AND status = :st"
        params: dict = {"tid": tenant_id, "st": status}
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
