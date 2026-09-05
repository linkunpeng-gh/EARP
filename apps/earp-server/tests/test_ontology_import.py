"""Ontology bulk import — CSV templates + dry-run validation + execute w/ profile recompile.

兜底导入路径（ontology-layer-design §6）：实体/事实 CSV 导入。
覆盖：模板内容、干跑校验（类型/关系方向/JSON/编码重复/confidence）、干跑不写库、
真实导入 + facts 入库 + profile 联动重编（tech-debt #11 ① 场景）。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.infra.db import tenant_session
from earp_server.ontology import import_service, tbox_service


async def _seed_dd(engine: AsyncEngine, tid: str) -> None:
    async with tenant_session(engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, "
                "data_classification, status) "
                "VALUES ('equipment_data', :tid, '设备数据', '设备报警维护', 'internal', 'active'), "
                "('finance_data', :tid, '财务数据', '财务制度报销', 'internal', 'active') "
                "ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )


async def _engine(app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


def test_import_templates_content() -> None:
    """模板含说明头 + 示例行（用户不知道填什么的问题）。"""
    assert "entity_type_id" in import_service.ENTITIES_TEMPLATE
    assert "business_code" in import_service.ENTITIES_TEMPLATE
    assert "CNC-01" in import_service.ENTITIES_TEMPLATE  # 示例行
    assert "source_code" in import_service.FACTS_TEMPLATE
    assert "relation_type_id" in import_service.FACTS_TEMPLATE
    assert "manufactured_by" in import_service.FACTS_TEMPLATE


async def test_import_dry_run_valid_no_write(migrated: str, app_url: str) -> None:
    engine = await _engine(app_url)
    tid = "imp-t1"
    await tbox_service.init_tenant_tbox(engine, tid)
    await _seed_dd(engine, tid)

    ents = "equipment,CNC-01,CNC-01,\nsupplier,上海某精机,SUP-001,"
    facts = "CNC-01,manufactured_by,SUP-001,1.0"
    res = await import_service.import_abox(engine, tid, ents, facts, dry_run=True)

    assert res["entities"]["total"] == 2 and res["entities"]["ok"] == 2
    assert res["entities"]["errors"] == []
    assert res["facts"]["total"] == 1 and res["facts"]["ok"] == 1
    assert res["facts"]["errors"] == []

    # 干跑不写库
    async with tenant_session(engine, tid) as s:
        n = (await s.execute(text("SELECT count(*) FROM entities WHERE tenant_id = :t"), {"t": tid})).scalar()
    assert n == 0
    await engine.dispose()


async def test_import_dry_run_collects_errors(migrated: str, app_url: str) -> None:
    engine = await _engine(app_url)
    tid = "imp-t2"
    await tbox_service.init_tenant_tbox(engine, tid)
    await _seed_dd(engine, tid)

    ents = (
        "equipment,CNC-01,CNC-01,\n"  # 行1 OK（新格式：无数据域列）
        "supplier,上海某精机,SUP-001,\n"  # 行2 OK
        "no_such_type,X,X,equipment_data,\n"  # 行3 类型不存在（旧格式兼容解析）
        "equipment,A,A,no_such_dd,\n"  # 行4 域不存在（旧格式）
        "equipment,B,B,equipment_data,{bad json\n"  # 行5 旧格式域一致 + JSON 非法
        "equipment,CNC-01b,CNC-01,\n"  # 行6 同类型 code 重复
        "supplier,MM,MM,equipment_data,\n"  # 行7 旧格式：域存在但与类型不一致（supplier→supply_chain_data）
    )
    facts = (
        "CNC-01,no_such_rel,SUP-001,1.0\n"  # 行1 关系不存在
        "CNC-01,caused_by,SUP-001,1.0\n"  # 行2 方向错（caused_by source=alarm）
        "CNC-01,manufactured_by,MISSING,1.0\n"  # 行3 目标不存在
        "CNC-01,manufactured_by,SUP-001,1.5\n"  # 行4 confidence 越界
        "CNC-01,manufactured_by,CNC-01,1.0\n"  # 行5 目标类型错（equipment 不在 target=supplier）
    )
    res = await import_service.import_abox(engine, tid, ents, facts, dry_run=True)

    assert res["entities"]["total"] == 7 and res["entities"]["ok"] == 2
    reasons = {e["row"]: e["reason"] for e in res["entities"]["errors"]}
    assert "实体类型不存在" in reasons[3]
    assert "数据域不存在" in reasons[4]
    assert "JSON 对象" in reasons[5]
    assert "business_code 重复" in reasons[6]
    assert "数据域" in reasons[7] and "不一致" in reasons[7]  # 2026-09：旧格式域与类型不一致报行错

    assert res["facts"]["total"] == 5 and res["facts"]["ok"] == 0
    freasons = {e["row"]: e["reason"] for e in res["facts"]["errors"]}
    assert "关系类型不存在" in freasons[1]
    assert "源实体类型" in freasons[2]
    assert "不存在" in freasons[3]
    assert "confidence" in freasons[4]
    assert "目标实体类型" in freasons[5]
    await engine.dispose()


async def test_import_execute_writes_and_recompiles_profile(migrated: str, app_url: str) -> None:
    engine = await _engine(app_url)
    tid = "imp-t3"
    await tbox_service.init_tenant_tbox(engine, tid)
    await _seed_dd(engine, tid)

    ents = "equipment,CNC-01,CNC-01,\nsupplier,上海某精机,SUP-001,"
    facts = "CNC-01,manufactured_by,SUP-001,1.0"
    res = await import_service.import_abox(engine, tid, ents, facts, dry_run=False)

    assert res["entities"]["errors"] == [] and res["facts"]["errors"] == []

    # 实体 + 事实入库
    async with tenant_session(engine, tid) as s:
        n_ent = (await s.execute(text("SELECT count(*) FROM entities WHERE tenant_id = :t"), {"t": tid})).scalar()
        n_fact = (await s.execute(text("SELECT count(*) FROM facts WHERE tenant_id = :t"), {"t": tid})).scalar()
        # 2026-09：实例数据域自动取所属类型域（模板无域列）
        dds = {
            code: dd
            for code, dd in (
                await s.execute(
                    text(
                        "SELECT business_code, data_domain_id FROM entities "
                        "WHERE tenant_id = :t AND business_code IS NOT NULL"
                    ),
                    {"t": tid},
                )
            ).all()
        }
    assert n_ent == 2 and n_fact == 1
    assert dds == {"CNC-01": "equipment_data", "SUP-001": "supply_chain_data"}

    # profile 联动重编（tech-debt #11 ①）：CNC-01 profile 的 key_facts 含 manufactured_by
    async with tenant_session(engine, tid) as s:
        row = (
            await s.execute(
                text(
                    "SELECT p.entity_id, p.profile FROM entity_profiles p "
                    "JOIN entities e ON e.entity_id = p.entity_id "
                    "WHERE e.tenant_id = :t AND e.business_code = 'CNC-01'"
                ),
                {"t": tid},
            )
        ).first()
    assert row is not None, "import must recompile profile for involved entities"
    import json

    profile = json.loads(row.profile) if isinstance(row.profile, str) else row.profile
    rels = [kf["relation"] for kf in profile.get("key_facts", [])]
    assert "由…制造" in rels  # compile_profile 聚合的是 relation_types.name（中文名）
    await engine.dispose()


async def test_component_supply_belong_relations(migrated: str, app_url: str) -> None:
    """TBox 部件级关系缺口闭合（2026-08-15 方案 A）：component→supplier 供应、
    component→equipment 归属——导入校验应放行（原会被类型匹配拒绝）。"""
    engine = await _engine(app_url)
    tid = "imp-t4"
    await tbox_service.init_tenant_tbox(engine, tid)
    await _seed_dd(engine, tid)

    ents = "component,主轴轴承,CPN-1,\nequipment,CNC-01,CNC-01,\nsupplier,上海某精机,SUP-001,"
    facts = (
        "CPN-1,supplied_by,SUP-001,1.0\n"  # 部件由供应商供应（新增）
        "CPN-1,belongs_to,CNC-01,1.0\n"  # 部件属于设备（新增）
    )
    res = await import_service.import_abox(engine, tid, ents, facts, dry_run=True)
    assert res["entities"]["errors"] == []
    assert res["facts"]["total"] == 2 and res["facts"]["ok"] == 2, res["facts"]["errors"]
    await engine.dispose()


async def test_import_legacy_dd_column_validation(migrated: str, app_url: str) -> None:
    """2026-09（设计 2026-09-04 D7）：旧模板仍含 data_domain_id 列——
    与类型域一致放行（含 attributes 位置），不一致/不存在报行错；新格式 attributes 在列 4。"""
    engine = await _engine(app_url)
    tid = "imp-t5"
    await tbox_service.init_tenant_tbox(engine, tid)
    await _seed_dd(engine, tid)

    ents = (
        "equipment,L1,L1,equipment_data,\n"  # 旧格式：域一致（equipment→equipment_data）+ 无 attrs
        'equipment,L2,L2,equipment_data,{"a":1}\n'  # 旧格式：域一致 + attrs 在列 5
        'equipment,L3,L3,{"a":2}\n'  # 新格式：attrs 在列 4（JSON）
        "supplier,MM,MM,equipment_data,\n"  # 旧格式：域存在但与类型不一致
        "equipment,L4,L4,no_such_dd,\n"  # 旧格式：域不存在
    )
    res = await import_service.import_abox(engine, tid, ents, None, dry_run=True)
    assert res["entities"]["total"] == 5 and res["entities"]["ok"] == 3, res["entities"]["errors"]
    err_rows = {e["row"]: e["reason"] for e in res["entities"]["errors"]}
    assert "不一致" in err_rows[4]
    assert "数据域不存在" in err_rows[5]
    await engine.dispose()
