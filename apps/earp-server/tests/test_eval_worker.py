"""T1 — 跑分 worker 接入测试：队列消费 + heartbeat + stale 恢复。

覆盖（对齐任务书 Task 4）：
- 服务级直调保持（test_eval_service 既有 14 用例不动）；这里补队列路径与 stale。
- 真 worker 消费：enqueue eval.run → run_worker_async（wait=False 短跑）消费
  → eval_runs completed（routing + bigram stub，机制层对齐既有）。
- stale 恢复（D2 心跳方案）：running + 旧 heartbeat → failed + summary.error=
  interrupted；心跳新鲜 running / cancelled / completed 不动（不误杀）。
- heartbeat：run_eval_task 每 case 前调回调（job 内报到 = stale 判定依据）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from earp_server.config import Settings
from earp_server.infra.db import tenant_session
from earp_server.infra.task_queue import ProcrastinateTaskQueue
from earp_server.ontology import eval_jobs, eval_service
from tests.test_eval_service import _install_stub, _seed_tenant, _set_id


async def _ensure_tenant_row(migration_url: str, tid: str) -> None:
    """tenants 行（recover 逐租户扫描依赖；tenants 无 RLS，用迁移角色插）。"""
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO tenants (tenant_id, name, status) VALUES (:tid, 'eval-worker', 'active') "
                "ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
    await eng.dispose()


async def _insert_run(
    migration_url: str, *, run_id: str, tid: str, sid: str, status: str, heartbeat_age_s: int
) -> None:
    """直接插 eval_runs 行（BYPASSRLS 迁移角色，绕 RLS 断言用）。"""
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO eval_runs (run_id, tenant_id, eval_set_id, mode, status, summary, heartbeat_at) "
                "VALUES (:rid, :tid, :sid, 'rules', :st, '{}', :hb)"
            ),
            {
                "rid": run_id,
                "tid": tid,
                "sid": sid,
                "st": status,
                "hb": datetime.now(UTC) - timedelta(seconds=heartbeat_age_s),
            },
        )
    await eng.dispose()


# ── D2: stale 恢复（不误杀心跳新鲜在跑任务）────────────────────────────────
async def test_recover_stale_runs_marks_zombies_only(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "evr-stale"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "routing")
    await _ensure_tenant_row(migrated, tid)

    # 四类行：旧心跳 running（应恢复）/ 新心跳 running（不动）/ cancelled / completed（不动）
    await _insert_run(migrated, run_id="evr-old", tid=tid, sid=sid, status="running", heartbeat_age_s=7200)
    await _insert_run(migrated, run_id="evr-fresh", tid=tid, sid=sid, status="running", heartbeat_age_s=60)
    await _insert_run(migrated, run_id="evr-cancelled", tid=tid, sid=sid, status="cancelled", heartbeat_age_s=7200)
    await _insert_run(migrated, run_id="evr-completed", tid=tid, sid=sid, status="completed", heartbeat_age_s=7200)

    n = await eval_service.recover_stale_runs(engine, ttl_seconds=3600)
    assert n == 1, n

    async with tenant_session(engine, tid) as session:
        for rid, expect in [
            ("evr-old", ("failed", {"error": "interrupted"})),
            ("evr-fresh", ("running", {})),
            ("evr-cancelled", ("cancelled", {})),
            ("evr-completed", ("completed", {})),
        ]:
            row = (
                await session.execute(text("SELECT status, summary FROM eval_runs WHERE run_id = :rid"), {"rid": rid})
            ).fetchone()
            assert row is not None, rid
            assert row.status == expect[0], (rid, row.status)
            assert row.summary == expect[1], (rid, row.summary)


# ── heartbeat: 每 case 前报到（stale 判定依据）─────────────────────────────
async def test_run_eval_task_heartbeat_per_case(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "evr-hb"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "routing")

    run = await eval_service.start_run(engine, tid, "u1", sid, mode="rules")
    # 心跳置为过期 → 若 heartbeat 生效，跑分过程中被刷新为新鲜
    m_eng = create_async_engine(migrated)
    async with m_eng.begin() as conn:
        await conn.execute(
            text("UPDATE eval_runs SET heartbeat_at = now() - interval '2 hours' WHERE run_id = :rid"),
            {"rid": run["run_id"]},
        )
    await m_eng.dispose()

    beats = 0

    async def beat() -> None:
        nonlocal beats
        beats += 1
        async with tenant_session(engine, tid) as session:
            await session.execute(
                text("UPDATE eval_runs SET heartbeat_at = now() WHERE run_id = :rid"), {"rid": run["run_id"]}
            )

    await eval_service.run_eval_task(engine, tid, run["run_id"], role_id="r-all", heartbeat=beat)

    assert beats == 5  # routing 内置 5 用例 → 每 case 前报到一次
    async with tenant_session(engine, tid) as session:
        row = (
            await session.execute(
                text("SELECT status, heartbeat_at FROM eval_runs WHERE run_id = :rid"), {"rid": run["run_id"]}
            )
        ).fetchone()
        assert row is not None
        assert row.status == "completed"
        assert (datetime.now(UTC) - row.heartbeat_at).total_seconds() < 60, "心跳应已被刷新"


# ── 真 worker 消费：enqueue → worker 短跑 → completed ──────────────────────
async def test_worker_consumes_eval_run_to_completion(migrated: str, app_url: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "evr-worker"
    await _seed_tenant(engine, migrated, tid)
    await eval_service.ensure_eval_sets(engine, tid)
    sid = await _set_id(tid, "routing")

    run = await eval_service.start_run(engine, tid, "u1", sid, mode="rules")

    # job 内 Settings() 构造 engine（worker 侧 env 一致性：EARP_DATABASE_URL）
    monkeypatch.setenv("EARP_DATABASE_URL", app_url)

    queue = ProcrastinateTaskQueue(Settings(database_url=app_url, app_env="test"))
    await queue.open()
    try:
        await queue.assert_schema()
        eval_jobs.register(queue)
        job_id = await queue.enqueue("eval.run", {"tenant_id": tid, "run_id": run["run_id"], "role_id": "r-all"})
        assert job_id

        # 真 worker 短跑：消费完队列即返回（spike drain 同款）
        await queue.app.run_worker_async(concurrency=1, wait=False, install_signal_handlers=False)
    finally:
        await queue.close()

    got = await eval_service.get_run(engine, tid, run["run_id"])
    assert got is not None
    assert got["status"] == "completed"
    assert got["summary"]["n"] == 5
    assert got["gates"]["overall"] is True
    assert len(got["results"]) == 5
