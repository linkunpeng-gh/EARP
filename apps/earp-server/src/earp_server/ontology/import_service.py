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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.ontology import abox_service

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
            r.relation_type_id: {"source": r.source_type.split(","), "target": r.target_type.split(",")}
            for r in rt
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
        existing = {
            r.business_code: {"entity_id": r.entity_id, "entity_type_id": r.entity_type_id} for r in ec
        }
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
                    engine, tenant_id, et, name,
                    business_code=code, attributes=attrs, data_domain_id=dd,
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
