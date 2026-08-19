"""T3 — 评估集治理测试：per-set 门槛 / 模板同步 / 导出导入 / 跑分进度。

覆盖（对齐任务书 Task 2/3/4）：
- 门槛 PUT：部分覆盖合并默认（防 gates 缺指标）、未知指标拒绝、数值范围、
  schema_violations 整数语义
- 模板同步：重建 builtin 用例 + custom 保留、删内置题后恢复、版本更新、
  非 builtin 拒绝
- 导出→导入往返一致（custom 集合，跨租户）
- 跑分进度：running 初始 0/N、完成后 100%、取消后冻结
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine

from earp_server.ontology import eval_service
from earp_server.ontology.eval_seed import SEED_VERSION, THRESHOLDS
from tests.test_eval_service import _install_stub, _seed_tenant, _set_id


async def _engine(app_url: str):
    return create_async_engine(app_url, pool_pre_ping=True)


# ── Task 2: per-set 门槛（合并默认 + 校验）────────────────────────────────
async def test_update_thresholds_merges_defaults(migrated: str, app_url: str) -> None:
    engine = await _engine(app_url)
    tid = "evg-thr"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "routing")

    # 部分覆盖：只传 dd_accuracy → 服务端合并默认（kb_accuracy 等保留）
    out = await eval_service.update_eval_set(engine, tid, sid, thresholds={"dd_accuracy": 0.8})
    assert out is not None
    assert out["thresholds"] == {**THRESHOLDS["routing"], "dd_accuracy": 0.8}
    assert out["enabled"] is True

    # 覆盖 + 启停一起
    out2 = await eval_service.update_eval_set(engine, tid, sid, enabled=False)
    assert out2 is not None
    assert out2["enabled"] is False
    got = await eval_service.get_eval_set(engine, tid, sid)
    assert got is not None
    assert got["enabled"] is False


async def test_update_thresholds_rejects_unknown_and_range(migrated: str, app_url: str) -> None:
    engine = await _engine(app_url)
    tid = "evg-thr2"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "routing")

    try:
        await eval_service.update_eval_set(engine, tid, sid, thresholds={"nope_metric": 0.5})
        raise AssertionError("未知指标应拒绝")
    except eval_service.EvalError as exc:
        assert "未知门槛指标" in str(exc)

    try:
        await eval_service.update_eval_set(engine, tid, sid, thresholds={"dd_accuracy": 1.5})
        raise AssertionError("数值越界应拒绝")
    except eval_service.EvalError as exc:
        assert "0-1" in str(exc)

    # schema_violations 允许非负整数（0 或 N），拒绝浮点/负——属 understanding 指标
    u_sid = await _set_id(tid, "understanding")
    try:
        await eval_service.update_eval_set(engine, tid, u_sid, thresholds={"schema_violations": 0.5})
        raise AssertionError("schema_violations 浮点应拒绝")
    except eval_service.EvalError:
        pass
    ok = await eval_service.update_eval_set(engine, tid, u_sid, thresholds={"schema_violations": 2})
    assert ok is not None
    assert ok["thresholds"]["schema_violations"] == 2


# ── Task 3: 模板同步 ──────────────────────────────────────────────────────
async def test_sync_builtin_rebuilds_and_keeps_custom(migrated: str, app_url: str) -> None:
    engine = await _engine(app_url)
    tid = "evg-sync"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "routing")

    # 内置集上手工加一条 custom 用例 + 删一条内置用例
    await eval_service.add_eval_case(
        engine, tid, sid, query="自定义：某设备的报警阈值", expected={"data_domain_id": "equipment_data"}
    )
    set_before = await eval_service.get_eval_set(engine, tid, sid)
    assert set_before is not None
    builtin = set_before["cases"]
    first = builtin[0]
    assert first["source"] == "builtin"
    await eval_service.delete_eval_case(engine, tid, first["case_id"])

    out = await eval_service.sync_builtin_set(engine, tid, sid)
    assert out is not None
    assert out["seed_version"] == SEED_VERSION

    got = await eval_service.get_eval_set(engine, tid, sid)
    assert got is not None
    # 5 条内置重建 + 1 条 custom 保留（删除的内置题恢复）
    assert len(got["cases"]) == 6, len(got["cases"])
    queries = [c["query"] for c in got["cases"]]
    assert "报销制度是什么" in queries  # 被删的内置题已恢复
    assert "自定义：某设备的报警阈值" in queries  # custom 保留
    sources = {c["source"] for c in got["cases"]}
    assert sources == {"builtin", "custom"}

    # 幂等：再同步一次题量不变
    await eval_service.sync_builtin_set(engine, tid, sid)
    got2 = await eval_service.get_eval_set(engine, tid, sid)
    assert got2 is not None
    assert len(got2["cases"]) == 6


async def test_sync_rejects_custom_set(migrated: str, app_url: str) -> None:
    engine = await _engine(app_url)
    tid = "evg-sync2"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    s = await eval_service.create_eval_set(engine, tid, kind="routing", name="my-custom")
    try:
        await eval_service.sync_builtin_set(engine, tid, s["eval_set_id"])
        raise AssertionError("custom 集合同步应拒绝")
    except eval_service.EvalError as exc:
        assert "仅内置" in str(exc)


# ── Task 3: 导出/导入往返 ─────────────────────────────────────────────────
async def test_export_import_roundtrip(migrated: str, app_url: str) -> None:
    engine = await _engine(app_url)
    tid_a, tid_b = "evg-exp-a", "evg-exp-b"
    await _seed_tenant(engine, migrated, tid_a)
    await _seed_tenant(engine, migrated, tid_b)
    await eval_service.ensure_eval_sets(engine, tid_a)

    # A 租户建 custom 集合（含门槛覆盖 + 2 用例）
    s = await eval_service.create_eval_set(engine, tid_a, kind="understanding", name="export-me")
    sid = s["eval_set_id"]
    await eval_service.add_eval_case(
        engine,
        tid_a,
        sid,
        query="CNC-01 由哪家供应商制造",
        expected={
            "intent": "RELATION",
            "entities": [{"mention": "CNC-01", "semantic_type": "equipment"}],
            "relations": ["manufactured_by"],
        },
    )
    await eval_service.add_eval_case(
        engine, tid_a, sid, query="设备总共有多少台", expected={"intent": "AGGREGATION"}
    )
    await eval_service.update_eval_set(engine, tid_a, sid, thresholds={"intent_accuracy": 0.7})

    payload = await eval_service.export_eval_set(engine, tid_a, sid)
    assert payload is not None
    assert payload["source"] == "custom"
    assert len(payload["cases"]) == 2
    assert payload["thresholds"]["intent_accuracy"] == 0.7
    assert "tenant" not in str(payload).lower() or "tenant" not in [k for k in payload]

    # B 租户导入 → custom 集合（id 自动生成）
    imported = await eval_service.import_eval_set(
        engine, tid_b,
        name=payload["name"], kind=payload["kind"], description=payload["description"],
        thresholds=payload["thresholds"], cases=payload["cases"],
    )
    assert imported["source"] == "custom"
    assert imported["case_count"] == 2

    got = await eval_service.get_eval_set(engine, tid_b, imported["eval_set_id"])
    assert got is not None
    assert got["name"] == "export-me"
    assert got["thresholds"]["intent_accuracy"] == 0.7
    assert got["thresholds"]["entity_recall"] == THRESHOLDS["understanding"]["entity_recall"]  # 合并默认
    assert len(got["cases"]) == 2
    assert all(c["source"] == "custom" for c in got["cases"])


async def test_import_validation(migrated: str, app_url: str) -> None:
    engine = await _engine(app_url)
    tid = "evg-imp"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)

    try:
        await eval_service.import_eval_set(engine, tid, name="x", kind="nope", cases=[])
        raise AssertionError("非法 kind 应拒绝")
    except eval_service.EvalError:
        pass
    try:
        await eval_service.import_eval_set(engine, tid, name="x", kind="routing", cases=[])
        raise AssertionError("空 cases 应拒绝")
    except eval_service.EvalError:
        pass
    try:
        await eval_service.import_eval_set(
            engine, tid, name="x", kind="routing",
            cases=[{"query": "q", "expected": {"no_domain": True}}],
        )
        raise AssertionError("routing 缺 data_domain_id 应拒绝")
    except eval_service.EvalError:
        pass


# ── Task 4: 跑分进度 ──────────────────────────────────────────────────────
async def test_run_progress_counts(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = await _engine(app_url)
    tid = "evg-prog"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "routing")

    run = await eval_service.start_run(engine, tid, "u1", sid, mode="rules")
    # running 初始：0/5
    early = await eval_service.get_run(engine, tid, run["run_id"])
    assert early is not None
    assert early["progress"] == {"completed": 0, "total": 5, "percent": 0}

    await eval_service.run_eval_task(engine, tid, run["run_id"], role_id="r-all")
    done = await eval_service.get_run(engine, tid, run["run_id"])
    assert done is not None
    assert done["status"] == "completed"
    assert done["progress"] == {"completed": 5, "total": 5, "percent": 100.0}


async def test_run_progress_frozen_after_cancel(migrated: str, app_url: str) -> None:
    engine = await _engine(app_url)
    tid = "evg-prog2"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "routing")

    run = await eval_service.start_run(engine, tid, "u1", sid, mode="rules")
    await eval_service.cancel_run(engine, tid, run["run_id"])
    got = await eval_service.get_run(engine, tid, run["run_id"])
    assert got is not None
    assert got["status"] == "cancelled"
    assert got["progress"] == {"completed": 0, "total": 5, "percent": 0}  # 冻结不回落
