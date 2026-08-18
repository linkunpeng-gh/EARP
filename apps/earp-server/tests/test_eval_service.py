"""B6 — 评估集管理 + 跑分引擎测试（服务函数级，对齐 test_tbox_approval 模式）。

覆盖：种子幂等 / 种子与 fixture 一致性 / 跨租户隔离 / 用例 CRUD / custom 集合 /
三 kind 跑分（routing bigram stub 机制层、understanding/planning rules 门槛）/
run 状态机 / 并发冲突 / 失败兜底。
"""

from __future__ import annotations

import hashlib
import pathlib
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from earp_server.infra.db import tenant_session
from earp_server.knowledge.chunk_service import create_chunks
from earp_server.knowledge.document_service import create_document
from earp_server.knowledge.routing import build_routing_index
from earp_server.ontology import abox_service, eval_service, tbox_service

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


# ── bigram stub（routing 机制层，对齐 test_routing）────────────────────────
class _BigramStubProvider:
    name = "bigram-stub"
    dim = 1024

    def _bigrams(self, t: str) -> set[str]:
        chars = re.findall(r"[\w\u4e00-\u9fff]", t.lower())
        return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            for bg in self._bigrams(t):
                vec[hashlib.md5(bg.encode()).digest()[0] % self.dim] += 1.0
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out


def _install_stub(monkeypatch) -> None:
    import earp_server.knowledge.embedding_service as svc
    import earp_server.knowledge.routing as routing

    provider = _BigramStubProvider()
    monkeypatch.setattr(routing, "get_embedding_provider", lambda: provider)
    monkeypatch.setattr(svc, "get_embedding_provider", lambda: provider)


async def _purge(migration_url: str) -> None:
    """共享语义 id（data_domains/knowledge_bases/roles 单列主键，debt #7 模式）。"""
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM chunks WHERE knowledge_base_id IN "
                "(SELECT knowledge_base_id FROM knowledge_bases WHERE data_domain_id = ANY(:dds))"
            ),
            {"dds": ["finance_data", "equipment_data", "hr_data"]},
        )
        await conn.execute(
            text(
                "DELETE FROM documents WHERE knowledge_base_id IN "
                "(SELECT knowledge_base_id FROM knowledge_bases WHERE data_domain_id = ANY(:dds))"
            ),
            {"dds": ["finance_data", "equipment_data", "hr_data"]},
        )
        await conn.execute(
            text("DELETE FROM knowledge_bases WHERE data_domain_id = ANY(:dds)"),
            {"dds": ["finance_data", "equipment_data", "hr_data"]},
        )
        await conn.execute(
            text("DELETE FROM data_domains WHERE data_domain_id = ANY(:dds)"),
            {"dds": ["finance_data", "equipment_data", "hr_data"]},
        )
        await conn.execute(text("DELETE FROM roles WHERE role_id = ANY(:rids)"), {"rids": ["r-all"]})
    await eng.dispose()


async def _seed_tenant(engine, migration_url: str, tid: str) -> None:
    """评估租户：DD + role + KB/docs + 路由索引 + TBox + 实体/事实（对齐既有 seed）。"""
    await _purge(migration_url)
    async with tenant_session(engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, data_classification, status) "
                "VALUES ('finance_data', :tid, '财务数据', '财务制度、报销与成本管理', 'internal', 'active'), "
                "('equipment_data', :tid, '设备数据', '设备运行、报警与维护', 'internal', 'active'), "
                "('hr_data', :tid, '人力资源', '员工、休假与公司政策', 'internal', 'active') "
                "ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES ('r-all', :tid, 'eval-tester', '{}', 'all', "
                "'[{\"data_domain_id\": \"finance_data\"}, {\"data_domain_id\": \"equipment_data\"}, "
                "{\"data_domain_id\": \"hr_data\"}]') ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
        kbs = [
            ("kb-fin", "费用报销流程手册", "finance_data", "报销标准与流程说明"),
            ("kb-alarm", "报警阈值配置", "equipment_data", "设备报警阈值设定"),
            ("kb-manual", "设备手册", "equipment_data", "设备结构、主轴轴承更换周期"),
            ("kb-policy", "公司政策", "hr_data", "员工休假政策"),
        ]
        for kid, name, dd, desc in kbs:
            await session.execute(
                text(
                    "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name, data_domain_id, description, "
                    "metadata_schema) VALUES (:kid, :tid, :name, :dd, :desc, '[]') ON CONFLICT DO NOTHING"
                ),
                {"kid": kid, "tid": tid, "name": name, "dd": dd, "desc": desc},
            )
    docs = [
        ("kb-fin", "报销制度v1", "财务部报销制度：差旅报销标准与流程。"),
        ("kb-fin", "2024报销标准", "2024年报销标准：住宿每天500元，餐饮每天100元。"),
        ("kb-alarm", "报警阈值配置说明", "设备报警阈值：主轴温度超过85度触发报警。"),
        ("kb-manual", "主轴轴承更换周期", "主轴轴承更换周期：每运行8000小时更换一次。"),
        ("kb-policy", "员工休假政策", "员工年假10天，病假凭证明，产假按国家规定。"),
    ]
    for kb, title, content in docs:
        doc = await create_document(engine, tid, kb, content, title=title)
        await create_chunks(engine, tid, doc["document_id"], content)
    await build_routing_index(engine, tid)

    await tbox_service.init_tenant_tbox(engine, tid)
    e = {
        "equip": await abox_service.upsert_entity(engine, tid, "equipment", "CNC-01", business_code="CNC-01"),
        "plant": await abox_service.upsert_entity(engine, tid, "plant", "华东一厂", business_code="PL-1"),
        "line": await abox_service.upsert_entity(engine, tid, "production_line", "A产线", business_code="LN-A"),
        "supplier": await abox_service.upsert_entity(engine, tid, "supplier", "上海某精机", business_code="SUP-1"),
        "emp": await abox_service.upsert_entity(engine, tid, "employee", "张工", business_code="EMP-1"),
        "alarm": await abox_service.upsert_entity(engine, tid, "alarm", "高温报警"),
        "comp": await abox_service.upsert_entity(engine, tid, "component", "主轴轴承", business_code="CMP-1"),
        "product": await abox_service.upsert_entity(engine, tid, "product", "P-100", business_code="P-100"),
    }
    await abox_service.add_fact(engine, tid, e["equip"]["entity_id"], "manufactured_by", e["supplier"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["equip"]["entity_id"], "located_in", e["plant"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["equip"]["entity_id"], "belongs_to", e["line"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["alarm"]["entity_id"], "caused_by", e["equip"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["comp"]["entity_id"], "belongs_to", e["equip"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["comp"]["entity_id"], "supplied_by", e["supplier"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["line"]["entity_id"], "responsible_for", e["emp"]["entity_id"])
    await abox_service.add_fact(engine, tid, e["equip"]["entity_id"], "maintained_by", e["emp"]["entity_id"])


async def _set_id(tid: str, kind: str) -> str:
    return f"evs-{tid}-{kind}"


# ── Task 1/2: 种子 ─────────────────────────────────────────────────────────
async def test_ensure_seeds_builtin_sets_idempotent(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ev-seed"
    await _seed_tenant(engine, migrated, tid)

    await eval_service.ensure_eval_sets(engine, tid)
    await eval_service.ensure_eval_sets(engine, tid)  # 幂等

    sets = await eval_service.list_eval_sets(engine, tid)
    assert len(sets) == 3, sets
    by_kind = {s["kind"]: s for s in sets}
    assert set(by_kind) == {"routing", "understanding", "planning"}
    assert by_kind["routing"]["case_count"] == 5
    assert by_kind["understanding"]["case_count"] >= 100
    assert by_kind["planning"]["case_count"] >= 100
    assert by_kind["routing"]["source"] == "builtin"


async def test_seed_matches_fixture(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ev-fixture"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)

    s = await eval_service.get_eval_set(engine, tid, await _set_id(tid, "routing"))
    assert s is not None and s["cases"][0]["query"] == "报销制度是什么"
    assert s["cases"][0]["expected"]["data_domain_id"] == "finance_data"
    assert s["cases"][0]["expected"]["knowledge_base_id"] == "费用报销流程手册"

    u = await eval_service.get_eval_set(engine, tid, await _set_id(tid, "understanding"))
    assert u is not None
    rel_case = next(c for c in u["cases"] if c["query"] == "CNC-01 由哪家供应商制造")
    assert rel_case["expected"]["intent"] == "RELATION"
    assert rel_case["expected"]["relations"] == ["manufactured_by"]


# ── 跨租户隔离 ─────────────────────────────────────────────────────────────
async def test_cross_tenant_isolation(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid_a, tid_b = "ev-iso-a", "ev-iso-b"
    await _seed_tenant(engine, migrated, tid_a)
    await eval_service.ensure_eval_sets(engine, tid_a)

    assert await eval_service.get_eval_set(engine, tid_b, await _set_id(tid_a, "routing")) is None
    await eval_service.ensure_eval_sets(engine, tid_b)
    sets_b = await eval_service.list_eval_sets(engine, tid_b)
    assert len(sets_b) == 3  # B 惰性种子自己的三套
    assert all(not s["eval_set_id"].startswith(f"evs-{tid_a}") for s in sets_b)
    # A 的集合在 B 视角不存在（RLS）
    assert await eval_service.get_eval_set(engine, tid_b, await _set_id(tid_a, "routing")) is None
    # B 的集合 A 也看不见
    assert await eval_service.get_eval_set(engine, tid_a, await _set_id(tid_b, "routing")) is None


# ── 用例 CRUD + custom 集合 ────────────────────────────────────────────────
async def test_case_crud(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ev-crud"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "routing")

    added = await eval_service.add_eval_case(
        engine, tid, sid, query="新产品发布流程", expected={"data_domain_id": "hr_data"}, note="自定义"
    )
    s = await eval_service.get_eval_set(engine, tid, sid)
    assert len(s["cases"]) == 6
    assert any(c["query"] == "新产品发布流程" for c in s["cases"])

    # 启用开关
    await eval_service.update_eval_case(engine, tid, added["case_id"], enabled=False)
    s = await eval_service.get_eval_set(engine, tid, sid)
    assert next(c for c in s["cases"] if c["case_id"] == added["case_id"])["enabled"] is False

    # 删除
    assert await eval_service.delete_eval_case(engine, tid, added["case_id"]) is True
    s = await eval_service.get_eval_set(engine, tid, sid)
    assert len(s["cases"]) == 5

    # expected 校验
    try:
        await eval_service.add_eval_case(engine, tid, sid, query="x", expected={})
        raise AssertionError("expected 校验应拒绝空 expected")
    except eval_service.EvalError as exc:
        assert "data_domain_id" in str(exc)


async def test_custom_eval_set(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ev-custom"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)

    created = await eval_service.create_eval_set(engine, tid, kind="understanding", name="我的理解评估")
    assert created["source"] == "custom"
    s = await eval_service.get_eval_set(engine, tid, created["eval_set_id"])
    assert s is not None and s["name"] == "我的理解评估" and s["cases"] == []
    try:
        await eval_service.create_eval_set(engine, tid, kind="nope", name="x")
        raise AssertionError("非法 kind 应拒绝")
    except eval_service.EvalError:
        pass


# ── 跑分（三 kind）─────────────────────────────────────────────────────────
async def test_routing_run_gates(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ev-rt"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "routing")

    run = await eval_service.start_run(engine, tid, "u1", sid, mode="rules")
    assert run["status"] == "running"
    await eval_service.run_eval_task(engine, tid, run["run_id"], role_id="r-all")

    got = await eval_service.get_run(engine, tid, run["run_id"])
    assert got["status"] == "completed"
    assert got["summary"]["n"] == 5
    assert got["summary"]["dd_accuracy"] >= 0.9, got["summary"]
    assert got["gates"]["dd_accuracy"] is True
    assert got["gates"]["overall"] is True
    assert len(got["results"]) == 5


async def test_understanding_run_gates(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ev-und"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "understanding")

    run = await eval_service.start_run(engine, tid, "u1", sid, mode="rules")
    await eval_service.run_eval_task(engine, tid, run["run_id"], role_id="r-all")

    got = await eval_service.get_run(engine, tid, run["run_id"])
    assert got["status"] == "completed"
    s = got["summary"]
    assert s["intent_accuracy"] >= 0.85, s
    assert s["entity_recall"] >= 0.90, s
    assert s["relation_accuracy"] >= 0.80, s
    assert s["schema_violations"] == 0, s
    assert got["gates"]["overall"] is True


async def test_understanding_run_reports_missing_entities_honestly(migrated: str, app_url: str) -> None:
    """无评估实体的租户 → entity_recall 如实为 0（回归：_aggregate 曾把期望数当命中数）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ev-und-empty"
    # 只建 TBox（无实体）——评估用例期望的实体（CNC-01 等）不存在
    await tbox_service.init_tenant_tbox(engine, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "understanding")

    run = await eval_service.start_run(engine, tid, "u1", sid, mode="rules")
    await eval_service.run_eval_task(engine, tid, run["run_id"], role_id="r-all")

    got = await eval_service.get_run(engine, tid, run["run_id"])
    assert got["status"] == "completed"
    s = got["summary"]
    # 期望实体几乎全部未命中（唯一命中 = ctx 指代消解用例，合法）——如实低分而非虚高
    assert s["entity_recall"] < 0.1, s
    assert got["gates"]["entity_recall"] is False


async def test_planning_run_gates(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ev-plan"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "planning")

    run = await eval_service.start_run(engine, tid, "u1", sid, mode="rules")
    await eval_service.run_eval_task(engine, tid, run["run_id"], role_id="r-all")

    got = await eval_service.get_run(engine, tid, run["run_id"])
    assert got["status"] == "completed"
    assert got["summary"]["strategy_hit_rate"] >= 0.95, got["summary"]
    assert got["gates"]["overall"] is True


# ── run 状态机 / 并发 / 失败兜底 ───────────────────────────────────────────
async def test_run_concurrency_conflict(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ev-conflict"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "planning")

    await eval_service.start_run(engine, tid, "u1", sid, mode="rules")  # running 中
    try:
        await eval_service.start_run(engine, tid, "u1", sid, mode="rules")
        raise AssertionError("running 中再跑应拒绝")
    except eval_service.EvalError as exc:
        assert "进行中" in str(exc)


async def test_run_failure_fallback(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ev-fail"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    # 跑一个不存在的 set → start_run 拒绝
    try:
        await eval_service.start_run(engine, tid, "u1", "evs-nope", mode="rules")
        raise AssertionError("不存在集合应拒绝")
    except eval_service.EvalError as exc:
        assert "评估集不存在" in str(exc)

    # 任务级失败兜底：start_run 后删除集合行 → run_eval_task 标记 failed + error
    sid = await _set_id(tid, "routing")
    run = await eval_service.start_run(engine, tid, "u1", sid, mode="rules")
    async with tenant_session(engine, tid) as session:
        await session.execute(text("DELETE FROM eval_sets WHERE eval_set_id = :sid"), {"sid": sid})
    await eval_service.run_eval_task(engine, tid, run["run_id"], role_id="r-all")
    got = await eval_service.get_run(engine, tid, run["run_id"])
    assert got["status"] == "failed"
    assert "评估集不存在" in got["summary"]["error"]

    # 空用例集 → 显式 failed（不做空跑通过）
    sid2 = await _set_id(tid, "planning")
    run2 = await eval_service.start_run(engine, tid, "u1", sid2, mode="rules")
    async with tenant_session(engine, tid) as session:
        await session.execute(
            text("UPDATE eval_cases SET enabled = FALSE WHERE eval_set_id = :sid"), {"sid": sid2}
        )
    await eval_service.run_eval_task(engine, tid, run2["run_id"], role_id="r-all")
    got2 = await eval_service.get_run(engine, tid, run2["run_id"])
    assert got2["status"] == "failed"
    assert "无启用" in got2["summary"]["error"]


async def test_run_cancel(migrated: str, app_url: str) -> None:
    """取消机制：running → cancelled；任务提前终止不覆盖；已完成幂等。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ev-cancel"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "planning")

    # 1) running → cancelled
    run = await eval_service.start_run(engine, tid, "u1", sid, mode="rules")
    out = await eval_service.cancel_run(engine, tid, run["run_id"])
    assert out["status"] == "cancelled"

    # 2) 取消后任务提前终止：不写 completed、不执行任何 case（第一轮检查即 return）
    await eval_service.run_eval_task(engine, tid, run["run_id"], role_id="r-all")
    got = await eval_service.get_run(engine, tid, run["run_id"])
    assert got["status"] == "cancelled"
    assert got["results"] == []

    # 3) 幂等：已取消再 cancel 返回 cancelled
    out2 = await eval_service.cancel_run(engine, tid, run["run_id"])
    assert out2["status"] == "cancelled"

    # 4) 已完成 run 的 cancel 幂等返回 completed（不破坏历史）
    run2 = await eval_service.start_run(engine, tid, "u1", sid, mode="rules")
    await eval_service.run_eval_task(engine, tid, run2["run_id"], role_id="r-all")
    got2 = await eval_service.get_run(engine, tid, run2["run_id"])
    assert got2["status"] == "completed"
    out3 = await eval_service.cancel_run(engine, tid, run2["run_id"])
    assert out3["status"] == "completed"
    # 取消不影响已完成结果
    got3 = await eval_service.get_run(engine, tid, run2["run_id"])
    assert got3["status"] == "completed" and len(got3["results"]) > 0

    # 5) 不存在 → None
    assert await eval_service.cancel_run(engine, tid, "evr-nope") is None


async def test_run_list_and_detail(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ev-list"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "planning")

    run = await eval_service.start_run(engine, tid, "u1", sid, mode="rules")
    await eval_service.run_eval_task(engine, tid, run["run_id"], role_id="r-all")

    runs = await eval_service.list_runs(engine, tid)
    assert len(runs) == 1 and runs[0]["status"] == "completed"
    runs_sid = await eval_service.list_runs(engine, tid, eval_set_id=sid)
    assert len(runs_sid) == 1
    # 最新 run 摘要挂在集合上
    sets = await eval_service.list_eval_sets(engine, tid)
    p = next(s for s in sets if s["kind"] == "planning")
    assert p["latest_run"] is not None and p["latest_run"]["status"] == "completed"
