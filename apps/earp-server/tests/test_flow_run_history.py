"""运行历史（tech-debt #17）测试。

Task 1（service 层）：finish_run 带 trace 落库 / list_runs 分页 / get_conversation_runs /
挂起（update_waiting）不写 trace。Task 2/5 扩展：flow_chat 终态写入 + 查询端点 + 权限。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.conversation import flow_runs
from earp_server.infra.db import tenant_session

TENANT = "runhist-t1"
APP = "app-runhist"
CONV = "conv-runhist"


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def _seed_run(engine: AsyncEngine, *, exec_id: str, conv_id: str = CONV, status: str = "running") -> None:
    await flow_runs.create_run(
        engine, TENANT, execution_id=exec_id, chat_app_id=APP, conversation_id=conv_id, flow_input={"query": "q"}
    )
    if status != "running":
        await flow_runs.finish_run(engine, TENANT, exec_id, status=status)


@pytest.fixture(scope="module", autouse=True)
async def _seed_app(app_engine: AsyncEngine) -> None:
    """flow_runs.chat_app_id → chat_apps FK：测试先建固定 id 应用（module 级一次）。"""
    async with tenant_session(app_engine, TENANT) as session:
        await session.execute(
            text(
                "INSERT INTO chat_apps (chat_app_id, tenant_id, name, description, orchestration) "
                "VALUES (:id, :tid, '运行历史测试应用', '', 'auto') ON CONFLICT (chat_app_id) DO NOTHING"
            ),
            {"id": APP, "tid": TENANT},
        )


def _trace() -> list[dict]:
    return [
        {
            "node_id": "start",
            "status": "completed",
            "branch": None,
            "input": None,
            "output": {},
            "error": None,
            "error_code": None,
            "latency_ms": 1,
        },
        {
            "node_id": "l1",
            "status": "completed",
            "branch": None,
            "input": {"q": "hi"},
            "output": {"text": "ok"},
            "error": None,
            "error_code": None,
            "latency_ms": 12,
        },
    ]


async def test_finish_run_persists_trace(app_engine: AsyncEngine) -> None:
    """终态带 trace → 落库可读（JSON 结构一致）。"""
    exec_id = "r-trace-1"
    await _seed_run(app_engine, exec_id=exec_id)
    await flow_runs.finish_run(app_engine, TENANT, exec_id, status="completed", trace=_trace())

    runs = await flow_runs.get_conversation_runs(app_engine, TENANT, CONV)
    run = next(r for r in runs if r["execution_id"] == exec_id)
    assert run["status"] == "completed"
    assert run["finished_at"] is not None
    assert run["trace"] == _trace()
    assert run["trace"][1]["latency_ms"] == 12


async def test_finish_run_without_trace_keeps_default(app_engine: AsyncEngine) -> None:
    """不传 trace → 保持现值（存量调用/超时扫描兜底路径）。"""
    exec_id = "r-trace-2"
    await _seed_run(app_engine, exec_id=exec_id)
    await flow_runs.finish_run(app_engine, TENANT, exec_id, status="failed")
    runs = await flow_runs.get_conversation_runs(app_engine, TENANT, CONV)
    run = next(r for r in runs if r["execution_id"] == exec_id)
    assert run["trace"] == {}


async def test_update_waiting_does_not_write_trace(app_engine: AsyncEngine) -> None:
    """挂起（update_waiting）不写 trace——trace 只属于终态（D2）。"""
    exec_id = "r-wait-1"
    await _seed_run(app_engine, exec_id=exec_id)
    await flow_runs.update_waiting(
        app_engine, TENANT, exec_id, pending_node_id="h1", node_state={"start": {"status": "completed"}}, attempts=1
    )
    runs = await flow_runs.get_conversation_runs(app_engine, TENANT, CONV)
    run = next(r for r in runs if r["execution_id"] == exec_id)
    assert run["status"] == "waiting_human"
    assert run["pending_node_id"] == "h1"
    assert run["trace"] == {}


async def test_list_runs_pagination_and_order(app_engine: AsyncEngine) -> None:
    """应用维度分页：倒序 + limit/offset + 不含 node_state/flow_input（列表摘要）。"""
    page_app = "app-runhist-page"
    async with tenant_session(app_engine, TENANT) as session:
        await session.execute(
            text(
                "INSERT INTO chat_apps (chat_app_id, tenant_id, name, description, orchestration) "
                "VALUES (:id, :tid, '分页测试', '', 'auto') ON CONFLICT (chat_app_id) DO NOTHING"
            ),
            {"id": page_app, "tid": TENANT},
        )
    for i in range(3):
        await flow_runs.create_run(
            app_engine,
            TENANT,
            execution_id=f"r-list-{i}",
            chat_app_id=page_app,
            conversation_id=f"conv-p-{i}",
            flow_input={"query": "q"},
        )
        await flow_runs.finish_run(app_engine, TENANT, f"r-list-{i}", status="completed", trace=_trace())

    page1 = await flow_runs.list_runs(app_engine, TENANT, page_app, limit=2, offset=0)
    assert len(page1) == 2
    assert [r["execution_id"] for r in page1] == ["r-list-2", "r-list-1"]  # 倒序
    page2 = await flow_runs.list_runs(app_engine, TENANT, page_app, limit=2, offset=2)
    assert [r["execution_id"] for r in page2] == ["r-list-0"]
    # 列表摘要不含执行中间态（详情页不需要 node_state/flow_input）
    assert all("node_state" not in r and "flow_input" not in r for r in page1)
    assert page1[0]["trace"] == _trace()
    # 跨应用/跨租户隔离
    assert await flow_runs.list_runs(app_engine, TENANT, "app-other") == []
    assert await flow_runs.list_runs(app_engine, "runhist-other", page_app) == []


# ── Task 5：flow_chat 集成（终态 trace 落库 / 恢复路径 / failed / timeout 转译） ──


async def _seed_flow_user(engine: AsyncEngine) -> None:
    """flow_chat 会话创建需要 users 行（conversations FK）。"""
    async with tenant_session(engine, TENANT) as session:
        await session.execute(
            text(
                "INSERT INTO users (user_id, tenant_id, name, email) "
                "VALUES ('u-flow', :t, 'flow', NULL) ON CONFLICT (user_id) DO NOTHING"
            ),
            {"t": TENANT},
        )


async def test_flow_chat_persists_trace_on_completed(app_engine: AsyncEngine) -> None:
    """挂起 202 → 恢复 → completed：最终 trace 落库且与响应同源；attempts=2。"""
    from earp_server.conversation.chat_app_service import create_chat_app
    from earp_server.conversation.chat_service import flow_chat
    from tests.test_flow_approval import FakeLLM, _approval_flow, _settings

    await _seed_flow_user(app_engine)
    app = await create_chat_app(
        app_engine,
        TENANT,
        "u-flow",
        "历史-完成",
        orchestration="flow",
        flow_schema=_approval_flow(extra_llm_after=False),
    )
    first = await flow_chat(
        app_engine, TENANT, "u-flow", "r-flow", app, "报销审批", None, base_llm=FakeLLM(), settings=_settings()
    )
    assert first["status"] == "waiting_human"
    # 挂起期间：run 在 flow_runs 且 trace 为空（D2：挂起不写 trace）
    waiting = await flow_runs.get_waiting_run(app_engine, TENANT, first["conversation_id"])
    assert waiting is not None and waiting["trace"] == {}

    second = await flow_chat(
        app_engine,
        TENANT,
        "u-flow",
        "r-flow",
        app,
        "同意",
        first["conversation_id"],
        base_llm=FakeLLM(),
        settings=_settings(),
    )
    assert second["status"] == "completed"
    runs = await flow_runs.get_conversation_runs(app_engine, TENANT, first["conversation_id"])
    assert len(runs) == 1  # 恢复复用同一 execution_id
    run = runs[0]
    assert run["status"] == "completed"
    assert run["trace"] == second["trace"], "落库 trace 与响应同源"
    assert run["attempts"] >= 1  # attempts 表示挂起次数（恢复完成不额外递增）
    assert run["finished_at"] is not None


async def test_flow_chat_persists_trace_on_failed(app_engine: AsyncEngine) -> None:
    """恢复路径节点失败（LLM 抛错）→ failed：trace 含 error 落库。"""
    from earp_server.connector import ConnectorError
    from earp_server.conversation.chat_app_service import create_chat_app
    from earp_server.conversation.chat_service import flow_chat
    from tests.test_flow_approval import _approval_flow, _settings

    class _FailLLM:
        async def complete(self, prompt, **kwargs):
            raise ConnectorError("连接失败")

    app = await create_chat_app(
        app_engine,
        TENANT,
        "u-flow",
        "历史-失败",
        orchestration="flow",
        flow_schema=_approval_flow(extra_llm_after=True),  # h1 后接 l1(llm)
    )
    first = await flow_chat(
        app_engine, TENANT, "u-flow", "r-flow", app, "q", None, base_llm=_FailLLM(), settings=_settings()
    )
    assert first["status"] == "waiting_human"
    second = await flow_chat(
        app_engine,
        TENANT,
        "u-flow",
        "r-flow",
        app,
        "同意",
        first["conversation_id"],
        base_llm=_FailLLM(),
        settings=_settings(),
    )
    assert second["status"] == "failed"
    runs = await flow_runs.get_conversation_runs(app_engine, TENANT, first["conversation_id"])
    run = runs[0]
    assert run["status"] == "failed"
    l1 = next((t for t in run["trace"] if t["node_id"] == "l1"), None)
    assert l1 is not None and l1["status"] == "failed"
    assert l1.get("error")  # 节点错误可见


async def test_timeout_translates_node_state_to_trace(app_engine: AsyncEngine) -> None:
    """超时扫描（expire_waiting_approvals）：node_state → 同构 trace 落库。"""
    await _seed_flow_user(app_engine)
    async with tenant_session(app_engine, TENANT) as session:
        # expire_waiting_approvals 逐租户扫描（遍历 tenants 表）——先注册租户
        await session.execute(
            text("INSERT INTO tenants (tenant_id, name) VALUES (:t, 'runhist') ON CONFLICT (tenant_id) DO NOTHING"),
            {"t": TENANT},
        )
        await session.execute(
            text(
                "INSERT INTO conversations (conversation_id, tenant_id, user_id, title, chat_app_id) "
                "VALUES ('conv-timeout', :t, 'u-flow', '超时会话', :a)"
            ),
            {"t": TENANT, "a": APP},
        )
    await flow_runs.create_run(
        app_engine,
        TENANT,
        execution_id="run-timeout-1",
        chat_app_id=APP,
        conversation_id="conv-timeout",
        flow_input={"query": "q"},
    )
    await flow_runs.update_waiting(
        app_engine,
        TENANT,
        "run-timeout-1",
        pending_node_id="h1",
        node_state={
            "start": {"status": "completed", "output": {}},
            "h1": {"status": "completed", "output": {"reply": "?"}},
        },
        attempts=1,
    )
    timed_out = await flow_runs.expire_waiting_approvals(app_engine, ttl_seconds=-1)  # cutoff 在未来 → 必超时
    assert any(r["execution_id"] == "run-timeout-1" for r in timed_out)
    runs = await flow_runs.get_conversation_runs(app_engine, TENANT, "conv-timeout")
    run = runs[0]
    assert run["status"] == "timeout"
    assert {t["node_id"] for t in run["trace"]} == {"start", "h1"}  # 由 node_state 转译
    assert run["trace"][0]["status"] == "completed"
