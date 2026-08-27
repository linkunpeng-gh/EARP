"""Ontology bulk import — CSV templates (entities + facts) with dry-run validation.

兜底导入路径（ontology-layer-design §6：无中台场景 CSV 文件导入）。
Flow: parse CSV → validate (TBox / DD / type-match / business_code) → dry_run
returns per-row errors → execute (upsert_entity + add_fact + profile recompile,
tech-debt #11 ① 的写时失效场景：导入后重编受影响实体 profile).
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session
from earp_server.ontology import abox_service, connector_service, data_adapter, tbox_service

logger = logging.getLogger(__name__)

# 模板（含说明头注释 + 示例行）——下载后 Excel 可直接编辑
ENTITIES_TEMPLATE = """# EARP 实体导入模板（entities.csv）
# 列: entity_type_id, name, business_code, data_domain_id, attributes(JSON)
# entity_type_id 必须是已注册类型（如 equipment/supplier/plant/employee...，见 GET /v1/ontology/entity-types）
# business_code 必填：业务编码，作为 facts 引用的锚点（同类型内唯一）
# data_domain_id 必须已存在；attributes 可选，JSON 对象
equipment,CNC-01,CNC-01,equipment_data,{"model":"XK-500"}
supplier,上海某精机,SUP-001,equipment_data,
"""

FACTS_TEMPLATE = """# EARP 事实导入模板（facts.csv）
# 列: source_code, relation_type_id, target_code, confidence
# source_code/target_code 引用 entities 的 business_code（同批导入或已存在实体）
# relation_type_id 必须是已注册关系；源/目标实体类型必须匹配该关系的类型约束
# confidence 0-1（规则导入=1.0；LLM 抽取 <1.0），可选默认 1.0
CNC-01,manufactured_by,SUP-001,1.0
"""

_MAX_CSV_BYTES = 2 * 1024 * 1024


def parse_csv_rows(content: str) -> list[tuple[int, list[str]]]:
    """Parse CSV: skip blank lines and '#' comment lines. Returns [(row_no, cells)]."""
    rows: list[tuple[int, list[str]]] = []
    reader = csv.reader(io.StringIO(content))
    for i, row in enumerate(reader, start=1):
        cells = [c.strip() for c in row]
        if not cells or not any(cells):
            continue
        if cells[0].startswith("#"):
            continue
        rows.append((i, cells))
    return rows


async def _load_tbox(engine: AsyncEngine, tenant_id: str) -> tuple[dict, dict, set[str], dict]:
    """TBox (entity_types kind / relation_types src+tgt sets) + DD ids + existing
    business_code → {entity_id, entity_type_id} map, for validation."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        et = await conn.execute(
            text("SELECT entity_type_id, kind FROM entity_types WHERE tenant_id = :tid AND status = 'active'"),
            {"tid": tenant_id},
        )
        entity_types = {r.entity_type_id: r.kind for r in et}
        rt = await conn.execute(
            text(
                "SELECT relation_type_id, source_type, target_type FROM relation_types "
                "WHERE tenant_id = :tid AND status = 'active'"
            ),
            {"tid": tenant_id},
        )
        relation_types = {
            r.relation_type_id: {"source": r.source_type.split(","), "target": r.target_type.split(",")} for r in rt
        }
        dd = await conn.execute(
            text("SELECT data_domain_id FROM data_domains WHERE tenant_id = :tid"), {"tid": tenant_id}
        )
        dd_ids = {r.data_domain_id for r in dd}
        ec = await conn.execute(
            text(
                "SELECT business_code, entity_type_id, entity_id FROM entities "
                "WHERE tenant_id = :tid AND status = 'active' AND business_code IS NOT NULL"
            ),
            {"tid": tenant_id},
        )
        existing = {r.business_code: {"entity_id": r.entity_id, "entity_type_id": r.entity_type_id} for r in ec}
        return entity_types, relation_types, dd_ids, existing


def _validate_entities(
    rows: list[tuple[int, list[str]]],
    entity_types: dict,
    dd_ids: set[str],
) -> tuple[list[tuple[int, list[str], dict]], list[dict]]:
    valid: list[tuple[int, list[str], dict]] = []
    errors: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row_no, cells in rows:
        if len(cells) < 4:
            errors.append(
                {
                    "row": row_no,
                    "reason": "列数不足（需要 entity_type_id,name,business_code,data_domain_id[,attributes]）",
                }
            )
            continue
        et, name, code, dd = cells[0], cells[1], cells[2], cells[3]
        if et not in entity_types:
            errors.append({"row": row_no, "reason": f"实体类型不存在: {et}"})
            continue
        if entity_types[et] != "object":
            errors.append({"row": row_no, "reason": f"实体类型不是 object（concept/metric 不走 ABox 事实导入）: {et}"})
            continue
        if not name or not code:
            errors.append({"row": row_no, "reason": "name/business_code 不能为空"})
            continue
        if dd not in dd_ids:
            errors.append({"row": row_no, "reason": f"数据域不存在: {dd}"})
            continue
        attrs: dict = {}
        attrs_raw = cells[4] if len(cells) > 4 else ""
        if attrs_raw.strip():
            try:
                attrs = json.loads(attrs_raw)
                if not isinstance(attrs, dict):
                    raise ValueError("not a JSON object")
            except Exception:
                errors.append({"row": row_no, "reason": f"attributes 不是合法 JSON 对象: {attrs_raw}"})
                continue
        key = (et, code)
        if key in seen:
            errors.append({"row": row_no, "reason": f"business_code 重复（同类型内）: {code}"})
            continue
        seen.add(key)
        valid.append((row_no, cells, attrs))
    return valid, errors


def _validate_facts(
    rows: list[tuple[int, list[str]]],
    relation_types: dict,
    entity_map: dict,
) -> list[tuple[int, list[str], float]]:
    """entity_map: business_code → {entity_id, entity_type_id}（本次解析 + 已存在实体）。"""
    valid: list[tuple[int, list[str], float]] = []
    errors: list[dict] = []
    for row_no, cells in rows:
        if len(cells) < 3:
            errors.append(
                {"row": row_no, "reason": "列数不足（需要 source_code,relation_type_id,target_code[,confidence]）"}
            )
            continue
        src_code, rel, tgt_code = cells[0], cells[1], cells[2]
        if rel not in relation_types:
            errors.append({"row": row_no, "reason": f"关系类型不存在: {rel}"})
            continue
        if src_code not in entity_map:
            errors.append({"row": row_no, "reason": f"源实体 business_code 不存在（本批或库内）: {src_code}"})
            continue
        if tgt_code not in entity_map:
            errors.append({"row": row_no, "reason": f"目标实体 business_code 不存在（本批或库内）: {tgt_code}"})
            continue
        s = entity_map[src_code]
        t = entity_map[tgt_code]
        r = relation_types[rel]
        if s["entity_type_id"] not in r["source"]:
            errors.append(
                {"row": row_no, "reason": f"源实体类型 {s['entity_type_id']} 不在关系 {rel} 的源类型集合 {r['source']}"}
            )
            continue
        if t["entity_type_id"] not in r["target"]:
            errors.append(
                {
                    "row": row_no,
                    "reason": f"目标实体类型 {t['entity_type_id']} 不在关系 {rel} 的目标类型集合 {r['target']}",
                }
            )
            continue
        conf_raw = cells[3] if len(cells) > 3 else "1.0"
        try:
            conf = float(conf_raw)
            if not 0 <= conf <= 1:
                raise ValueError
        except Exception:
            errors.append({"row": row_no, "reason": f"confidence 不是 0-1 数字: {conf_raw}"})
            continue
        valid.append((row_no, cells, conf))
    return valid, errors


async def import_abox(
    engine: AsyncEngine,
    tenant_id: str,
    entities_csv: str | None,
    facts_csv: str | None,
    *,
    dry_run: bool = True,
) -> dict:
    """导入入口：解析 → 校验 → （非干跑）写入 + profile 重编。

    Returns {"dry_run", "entities": {total, ok, errors}, "facts": {...}}。
    """
    entity_types, relation_types, dd_ids, existing = await _load_tbox(engine, tenant_id)
    entity_map: dict = {code: dict(v) for code, v in existing.items()}

    ent_result = {"total": 0, "ok": 0, "errors": []}
    fact_result = {"total": 0, "ok": 0, "errors": []}

    # ── entities ──
    if entities_csv and entities_csv.strip():
        rows = parse_csv_rows(entities_csv)
        valid_ents, ent_errors = _validate_entities(rows, entity_types, dd_ids)
        ent_result = {"total": len(rows), "ok": len(valid_ents), "errors": ent_errors}
        if dry_run:
            for _, cells, _ in valid_ents:
                entity_map[cells[2]] = {"entity_id": None, "entity_type_id": cells[0]}
        else:
            for _, cells, attrs in valid_ents:
                et, name, code, dd = cells[0], cells[1], cells[2], cells[3]
                ent = await abox_service.upsert_entity(
                    engine,
                    tenant_id,
                    et,
                    name,
                    business_code=code,
                    attributes=attrs,
                    data_domain_id=dd,
                )
                entity_map[code] = {"entity_id": ent["entity_id"], "entity_type_id": et}

    # ── facts ──
    if facts_csv and facts_csv.strip():
        rows = parse_csv_rows(facts_csv)
        valid_facts, fact_errors = _validate_facts(rows, relation_types, entity_map)
        fact_result = {"total": len(rows), "ok": len(valid_facts), "errors": fact_errors}
        if not dry_run:
            recompile_ids: set[str] = set()
            for _, cells, conf in valid_facts:
                s = entity_map[cells[0]]
                t = entity_map[cells[2]]
                await abox_service.add_fact(
                    engine, tenant_id, s["entity_id"], cells[1], t["entity_id"], confidence=conf
                )
                recompile_ids.update([s["entity_id"], t["entity_id"]])
            # profile 联动：涉及实体重编（写时失效，tech-debt #11 ①）
            for eid in recompile_ids:
                try:
                    await abox_service.compile_profile(engine, tenant_id, eid)
                except Exception:
                    logger.warning("import: profile recompile failed for %s", eid, exc_info=True)

    return {"dry_run": dry_run, "entities": ent_result, "facts": fact_result}


# ── M3 中台对接：数据源注册（B1，D2/G5）─────────────────────────────────────

_RULE_COLS = (
    "data_source_id, tenant_id, connector_id, entity_type_id, source_mode, "
    "field_mapping, incremental, status, last_synced_at, last_sync_status, created_at"
)


def _rule_public(row) -> dict:
    return {
        "data_source_id": row["data_source_id"],
        "connector_id": row["connector_id"],
        "entity_type_id": row["entity_type_id"],
        "source_mode": row["source_mode"],
        "field_mapping": row["field_mapping"],
        "incremental": row["incremental"] or {},
        "status": row["status"],
        "last_synced_at": row["last_synced_at"].isoformat() if row["last_synced_at"] else None,
        "last_sync_status": row["last_sync_status"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def register_data_source(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    connector_id: str,
    entity_type_id: str,
    source_mode: str,
    field_mapping: dict,
    incremental: dict | None = None,
) -> dict | None:
    """注册数据源 → import_rules 落库（MappingRule 持久化，定时同步复用）。

    校验（B1）：connector 存在且 active；entity_type 存在；virtual → kind=metric（G1）；
    field_mapping 必含 business_code_field + name_field。
    重复（同 connector+entity_type+source_mode）→ None（调用方 409）。
    """
    connector = await connector_service.get_connector(engine, tenant_id, connector_id)
    if connector is None:
        raise ValueError(f"connector 不存在: {connector_id}")
    if connector["status"] != "active":
        raise ValueError(f"connector 未启用: {connector_id}")
    types = await tbox_service.list_entity_types(engine, tenant_id)
    et = next((t for t in types if t["entity_type_id"] == entity_type_id), None)
    if et is None:
        raise ValueError(f"entity_type 不存在: {entity_type_id}")
    if source_mode not in ("virtual", "synced"):
        raise ValueError("source_mode 必须是 virtual 或 synced")
    if source_mode == "virtual" and et.get("kind") != "metric":
        raise ValueError("virtual 数据源仅支持 kind=metric 的实体类型（G1：object virtual 留二期）")
    if not field_mapping.get("business_code_field") or not field_mapping.get("name_field"):
        raise ValueError("field_mapping 必须包含 business_code_field 和 name_field")

    ds_id = f"ds-{uuid.uuid4().hex[:12]}"
    async with tenant_session(engine, tenant_id) as session:
        dup = await session.execute(
            text(
                "SELECT 1 FROM import_rules WHERE tenant_id = :tid AND connector_id = :cid "
                "AND entity_type_id = :et AND source_mode = :sm"
            ),
            {"tid": tenant_id, "cid": connector_id, "et": entity_type_id, "sm": source_mode},
        )
        if dup.first():
            return None
        await session.execute(
            text(
                "INSERT INTO import_rules (data_source_id, tenant_id, connector_id, "
                "entity_type_id, source_mode, field_mapping, incremental) "
                "VALUES (:id, :tid, :cid, :et, :sm, :fm, :inc)"
            ),
            {
                "id": ds_id,
                "tid": tenant_id,
                "cid": connector_id,
                "et": entity_type_id,
                "sm": source_mode,
                "fm": json.dumps(field_mapping),
                "inc": json.dumps(incremental or {}),
            },
        )
    return await get_data_source(engine, tenant_id, ds_id)


async def get_data_source(engine: AsyncEngine, tenant_id: str, data_source_id: str) -> dict | None:
    async with tenant_session(engine, tenant_id) as session:
        row = await session.execute(
            text(f"SELECT {_RULE_COLS} FROM import_rules WHERE data_source_id = :id AND tenant_id = :tid"),
            {"id": data_source_id, "tid": tenant_id},
        )
        r = row.mappings().first()
        return _rule_public(r) if r else None


async def list_data_sources(engine: AsyncEngine, tenant_id: str) -> list[dict]:
    async with tenant_session(engine, tenant_id) as session:
        rows = await session.execute(
            text(f"SELECT {_RULE_COLS} FROM import_rules WHERE tenant_id = :tid ORDER BY created_at"),
            {"tid": tenant_id},
        )
        return [_rule_public(r) for r in rows.mappings()]


async def mark_sync_state(
    engine: AsyncEngine,
    tenant_id: str,
    data_source_id: str,
    *,
    status: str,
    synced_at: str | None = None,
) -> None:
    """同步状态回写（B2/B3）：last_sync_status 必更新；synced_at 传则写 last_synced_at。"""
    async with tenant_session(engine, tenant_id) as session:
        if synced_at:
            await session.execute(
                text(
                    "UPDATE import_rules SET last_sync_status = :st, last_synced_at = :ts "
                    "WHERE data_source_id = :id AND tenant_id = :tid"
                ),
                {"st": status, "ts": synced_at, "id": data_source_id, "tid": tenant_id},
            )
        else:
            await session.execute(
                text("UPDATE import_rules SET last_sync_status = :st WHERE data_source_id = :id AND tenant_id = :tid"),
                {"st": status, "id": data_source_id, "tid": tenant_id},
            )


# ── M3 中台对接：同步执行（B3）───────────────────────────────────────────────


async def _find_by_code(engine: AsyncEngine, tenant_id: str, entity_type_id: str, code: str) -> dict | None:
    """按 (entity_type, business_code) 精确查活跃实体（facts 目标反查用）。"""
    async with tenant_session(engine, tenant_id) as session:
        row = await session.execute(
            text(
                "SELECT entity_id FROM entities WHERE tenant_id = :tid "
                "AND entity_type_id = :et AND business_code = :code AND status = 'active'"
            ),
            {"tid": tenant_id, "et": entity_type_id, "code": code},
        )
        r = row.mappings().first()
        return {"entity_id": r["entity_id"]} if r else None


async def _fact_exists(engine: AsyncEngine, tenant_id: str, src: str, rel: str, tgt: str) -> bool:
    """活跃事实去重（同源/同关系/同目标且未失效）——二次同步不重复建 facts。"""
    async with tenant_session(engine, tenant_id) as session:
        row = await session.execute(
            text(
                "SELECT 1 FROM facts WHERE tenant_id = :tid AND source_entity_id = :s "
                "AND relation_type_id = :r AND target_entity_id = :t "
                "AND valid_to IS NULL AND status = 'active'"
            ),
            {"tid": tenant_id, "s": src, "r": rel, "t": tgt},
        )
        return row.first() is not None


async def sync_from_connector(
    engine: AsyncEngine,
    tenant_id: str,
    data_source_id: str,
    *,
    heartbeat=None,
    bus=None,
) -> dict:
    """同步执行（B3）：规则读取 → connector 配置解密 → adapter 取数 →
    逐行 upsert_entity（source_mode=synced + source_ref=data_source_id，business_code 幂等）
    → relations 规则生成 facts（A3 契约：target_field = 目标实体 business_code；活跃去重）
    → profile 联动（upsert_entity/add_fact 写时失效钩子）→ runtime.knowledge.synced 事件。

    返回 {data_source_id, rows, created, merged, facts_added, errors[]}；
    单行失败收集不中断；取数失败抛 ConnectorFetchError（调用方标 failed）。
    """
    ds = await get_data_source(engine, tenant_id, data_source_id)
    if ds is None:
        raise ValueError(f"数据源不存在: {data_source_id}")
    cfg = await connector_service.decrypt_config(engine, tenant_id, ds["connector_id"])
    if not cfg:
        raise ValueError("connector 配置为空/解密失败（数据源可能未配置 connector）")

    # 增量（A3 契约 §5）：since_field + 上次同步时间
    params: dict = {}
    inc = ds.get("incremental") or {}
    if inc.get("enabled") and inc.get("since_field") and ds.get("last_synced_at"):
        params["since"] = ds["last_synced_at"]

    rows = await data_adapter.fetch(cfg, params)

    # TBox 上下文：实体类型 DD（属性继承）+ 关系目标类型（目标实体创建用）
    types = await tbox_service.list_entity_types(engine, tenant_id)
    et = next((t for t in types if t["entity_type_id"] == ds["entity_type_id"]), {})
    dd_id = et.get("data_domain_id")
    rels = {r["relation_type_id"]: r for r in await tbox_service.list_relation_types(engine, tenant_id)}

    fm = ds["field_mapping"]
    created = merged = facts_added = 0
    errors: list[dict] = []
    for i, row in enumerate(rows):
        if heartbeat and i % 50 == 0:
            await heartbeat()
        try:
            code = row.get(fm.get("business_code_field"))
            if code is None or str(code) == "":
                errors.append({"row": i, "reason": "business_code 为空"})
                continue
            name = row.get(fm.get("name_field")) or code
            attrs = {k: row.get(v) for k, v in (fm.get("attr_fields") or {}).items() if row.get(v) is not None}
            ent = await abox_service.upsert_entity(
                engine,
                tenant_id,
                ds["entity_type_id"],
                str(name),
                business_code=str(code),
                attributes=attrs,
                source_mode="synced",
                source_ref=data_source_id,
                data_domain_id=dd_id,
            )
            if ent["merged"]:
                merged += 1
            else:
                created += 1

            # relations：target_field 的值 = 目标实体 business_code（A3 契约 §4.3）
            for rel in fm.get("relations") or []:
                target_code = row.get(rel.get("target_field"))
                if target_code is None or str(target_code) == "":
                    continue
                rtype = rels.get(rel.get("relation_type"))
                if rtype is None:
                    errors.append({"row": i, "reason": f"relation_type 不存在: {rel.get('relation_type')}"})
                    continue
                target = await _find_by_code(engine, tenant_id, rtype["target_type"], str(target_code))
                if target is None:
                    tgt = await abox_service.upsert_entity(
                        engine,
                        tenant_id,
                        rtype["target_type"],
                        str(target_code),
                        business_code=str(target_code),
                        source_mode="synced",
                        source_ref=data_source_id,
                        data_domain_id=dd_id,
                    )
                    target = tgt
                if await _fact_exists(engine, tenant_id, ent["entity_id"], rel["relation_type"], target["entity_id"]):
                    continue  # 活跃事实已存在 → 幂等跳过
                await abox_service.add_fact(
                    engine,
                    tenant_id,
                    ent["entity_id"],
                    rel["relation_type"],
                    target["entity_id"],
                    confidence=1.0,
                    source_ref=data_source_id,
                )
                facts_added += 1
        except Exception as e:  # noqa: BLE001 — 单行失败不中断整批
            errors.append({"row": i, "reason": str(e)})
            logger.warning("sync row %d failed: %s", i, e)

    # runtime.knowledge.synced 事件（EventBus 无白名单自由发布；bus 为空跳过）
    if bus is not None:
        from earp_server.infra.eventbus import CloudEvent

        bus.publish(
            CloudEvent(
                type="runtime.knowledge.synced",
                source="earp-server/ontology",
                tenant_id=tenant_id,
                data={
                    "data_source_id": data_source_id,
                    "rows": len(rows),
                    "created": created,
                    "merged": merged,
                    "facts_added": facts_added,
                },
            )
        )

    return {
        "data_source_id": data_source_id,
        "rows": len(rows),
        "created": created,
        "merged": merged,
        "facts_added": facts_added,
        "errors": errors,
    }
