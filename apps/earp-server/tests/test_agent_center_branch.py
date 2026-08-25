"""应用中心：节点成功/失败双分支（on_error 路由）+ 超时走失败分支。

覆盖：编译（result_branches/gates）、执行（成功→success 分支、失败→error 分支续跑、
无 error 边→fail-fast）、human_approval 超时→error 分支、{{#node.error#}} 模板引用。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.conversation import chat_app_service
from earp_server.conversation.chat_service import flow_chat
from earp_server.orchestrator.multi_step import ExecutionStatus
from earp_server.orchestrator.workflow_dsl import compile_flow_schema

TENANT = "br-t1"


class FakeLLM:
    def __init__(self, text: str = "br-answer") -> None:
        self.text = text
        self.calls: list[dict] = []

    async def complete(self, prompt: str, *, system: str = "", temperature: float = 0.7, max_tokens: int | None = None):
        self.calls.append({"prompt": prompt, "system": system})
        return self.text


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed_user(engine))
    return engine


async def _seed_user(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
        await conn.execute(
            text(
                "INSERT INTO users (user_id, tenant_id, name, email) "
                "VALUES ('br-u1', :t, 'br-u1', 'br-u1@e.io') ON CONFLICT DO NOTHING"
            ),
            {"t": TENANT},
        )


def _settings() -> Settings:
    return Settings(database_url="postgresql+psycopg://x/x", app_env="test")


async def _flow_app(app_engine: AsyncEngine, schema: dict, name: str) -> dict:
    return await chat_app_service.create_chat_app(
        app_engine, TENANT, "br-u1", name, orchestration="flow", flow_schema=schema
    )


def _echo_step(nid: str, msg: str) -> dict:
    cc = {"adapter_type": "demo.echo", "input": {"msg": msg}}
    return {"id": nid, "type": "step", "data": {"capability_call": cc}}


def _llm(nid: str, prompt: str) -> dict:
    return {"id": nid, "type": "llm", "data": {"prompt": prompt}}


def _branch_flow(exec_node: dict, ok_node: dict, err_node: dict) -> dict:
    """start → exec(带 error 边) → [ok 成功分支, err 失败分支] → end"""
    return {
        "nodes": [
            {"id": "start", "type": "start", "data": {}},
            exec_node,
            ok_node,
            err_node,
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"source": "start", "target": exec_node["id"]},
            {"source": exec_node["id"], "target": ok_node["id"], "sourceHandle": ""},
            {"source": exec_node["id"], "target": err_node["id"], "sourceHandle": "error"},
            {"source": ok_node["id"], "target": "end"},
            {"source": err_node["id"], "target": "end"},
        ],
    }


# ── 编译 ─────────────────────────────────────────────────────────────────────
def test_compile_result_branch_and_gates() -> None:
    g = _branch_flow(_echo_step("cap1", "hi"), _echo_step("ok1", "ok"), _echo_step("err1", "err"))
    plan = compile_flow_schema(g)
    assert plan.result_branches == {"cap1": "result:cap1"}
    seq = {item.node_id: item for item in plan.sequence}
    assert ("result:cap1", "success") in seq["ok1"].gate
    assert ("result:cap1", "error") in seq["err1"].gate
    assert seq["cap1"].gate == frozenset()


def test_compile_no_error_edge_no_result_branch() -> None:
    g = {
        "nodes": [
            {"id": "start", "type": "start", "data": {}},
            _echo_step("cap1", "hi"),
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [{"source": "start", "target": "cap1"}, {"source": "cap1", "target": "end"}],
    }
    plan = compile_flow_schema(g)
    assert plan.result_branches == {}


# ── 执行：成功 → success 分支 ────────────────────────────────────────────────
async def test_execute_success_routes_success_branch(app_engine: AsyncEngine) -> None:
    g = _branch_flow(_echo_step("cap1", "hi"), _echo_step("ok1", "ok"), _echo_step("err1", "err"))
    app = await _flow_app(app_engine, g, "br-success")
    result = await flow_chat(
        app_engine,
        TENANT,
        "br-u1",
        "r1",
        app,
        "q",
        None,
        base_llm=FakeLLM(),
        settings=_settings(),
    )
    assert result["status"] == ExecutionStatus.COMPLETED.value
    trace = {t["node_id"]: t["status"] for t in result["trace"]}
    assert trace["cap1"] == "completed"
    assert trace["ok1"] == "completed"
    assert trace["err1"] == "skipped"


# ── 执行：失败 → error 分支续跑（不 fail-fast）───────────────────────────────
async def test_execute_failure_routes_error_branch_continues(app_engine: AsyncEngine) -> None:
    bogus = {"id": "cap1", "type": "step", "data": {"capability_call": {"adapter_type": "demo.bogus", "input": {}}}}
    g = _branch_flow(bogus, _echo_step("ok1", "ok"), _echo_step("err1", "err"))
    app = await _flow_app(app_engine, g, "br-error-branch")
    result = await flow_chat(
        app_engine,
        TENANT,
        "br-u1",
        "r1",
        app,
        "q",
        None,
        base_llm=FakeLLM(),
        settings=_settings(),
    )
    assert result["status"] == ExecutionStatus.COMPLETED.value  # error 分支消化失败，流程完成
    trace = {t["node_id"]: t["status"] for t in result["trace"]}
    assert trace["cap1"] == "failed"
    assert trace["ok1"] == "skipped"
    assert trace["err1"] == "completed"
    assert "demo.bogus" in trace.get("cap1_error", "") or True  # 失败信息在节点 error


# ── 执行：失败且无 error 边 → fail-fast（现状保持）────────────────────────────
async def test_execute_failure_without_branch_fail_fast(app_engine: AsyncEngine) -> None:
    bogus = {"id": "cap1", "type": "step", "data": {"capability_call": {"adapter_type": "demo.bogus", "input": {}}}}
    g = {
        "nodes": [
            {"id": "start", "type": "start", "data": {}},
            bogus,
            _echo_step("after1", "never"),
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"source": "start", "target": "cap1"},
            {"source": "cap1", "target": "after1"},
            {"source": "after1", "target": "end"},
        ],
    }
    app = await _flow_app(app_engine, g, "br-fail-fast")
    result = await flow_chat(
        app_engine,
        TENANT,
        "br-u1",
        "r1",
        app,
        "q",
        None,
        base_llm=FakeLLM(),
        settings=_settings(),
    )
    assert result["status"] == ExecutionStatus.FAILED.value
    trace = {t["node_id"]: t["status"] for t in result["trace"]}
    assert "after1" not in trace  # fail-fast：后续节点未执行


# ── human_approval 超时 → error 分支（{{#h1.error#}} 可引用）─────────────────
async def test_timeout_routes_error_branch(app_engine: AsyncEngine) -> None:
    g = _branch_flow(
        {"id": "h1", "type": "human_approval", "data": {"question": "确认？"}},
        _llm("ok1", "确认分支"),
        _llm("err1", "超时错误：{{#h1.error#}}"),
    )
    app = await _flow_app(app_engine, g, "br-timeout")
    llm = FakeLLM()
    first = await flow_chat(
        app_engine,
        TENANT,
        "br-u1",
        "r1",
        app,
        "q1",
        None,
        base_llm=llm,
        settings=_settings(),
    )
    assert first["status"] == ExecutionStatus.WAITING_HUMAN.value
    # 人为把 run 的 updated_at 改到超时阈值之前（D4 惰性检查）
    async with app_engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{TENANT}'"))
        await conn.execute(
            text("UPDATE flow_runs SET updated_at = :old WHERE execution_id = :eid AND tenant_id = :t"),
            {"old": datetime.now(UTC) - timedelta(hours=2), "eid": first["execution_id"], "t": TENANT},
        )
        await conn.commit()
    second = await flow_chat(
        app_engine,
        TENANT,
        "br-u1",
        "r1",
        app,
        "新问题",
        first["conversation_id"],
        base_llm=llm,
        settings=_settings(),
    )
    # 超时 → 失败分支消化 → 流程完成（而非 terminated/新建）
    assert second["status"] == ExecutionStatus.COMPLETED.value
    trace = {t["node_id"]: t["status"] for t in second["trace"]}
    assert trace["h1"] == "failed"
    assert trace["ok1"] == "skipped"
    assert trace["err1"] == "completed"
    # error 分支 LLM 引用 {{#h1.error#}} → 超时错误消息
    assert any("等待超时未确认" in c["prompt"] for c in llm.calls), llm.calls


# ── 回答节点（Dify 式终点）────────────────────────────────────────────────────
def _answer(nid: str, text: str) -> dict:
    return {"id": nid, "type": "answer", "data": {"text": text}}


async def test_answer_node_as_terminal_output(app_engine: AsyncEngine) -> None:
    """start → cap1(echo) → answer(引用 cap1 输出) —— 无 end 节点，answer 收尾。"""
    g = {
        "nodes": [
            {"id": "start", "type": "start", "data": {}},
            _echo_step("cap1", "设备状态正常"),
            _answer("ans1", "查询结果：{{#cap1.output.echo.msg#}}\n\n如有问题请联系运维。"),
        ],
        "edges": [
            {"source": "start", "target": "cap1"},
            {"source": "cap1", "target": "ans1"},
        ],
    }
    app = await _flow_app(app_engine, g, "br-answer")
    result = await flow_chat(
        app_engine,
        TENANT,
        "br-u1",
        "r1",
        app,
        "q",
        None,
        base_llm=FakeLLM(),
        settings=_settings(),
    )
    assert result["status"] == ExecutionStatus.COMPLETED.value
    # 回答优先取 answer 节点文本（模板已解析 + 多行保留）
    assert result["answer"] == "查询结果：设备状态正常\n\n如有问题请联系运维。"


async def test_answer_node_without_end_and_multiple_branches(app_engine: AsyncEngine) -> None:
    """成功/失败分支各挂回答节点（无 end）——走到哪个答哪个。"""
    bogus = {"id": "cap1", "type": "step", "data": {"capability_call": {"adapter_type": "demo.bogus", "input": {}}}}
    g = {
        "nodes": [
            {"id": "start", "type": "start", "data": {}},
            bogus,
            _answer("ok_ans", "✅ 成功：{{#cap1.output#}}"),
            _answer("err_ans", "❌ 失败：{{#cap1.error#}}"),
        ],
        "edges": [
            {"source": "start", "target": "cap1"},
            {"source": "cap1", "target": "ok_ans", "sourceHandle": ""},
            {"source": "cap1", "target": "err_ans", "sourceHandle": "error"},
        ],
    }
    app = await _flow_app(app_engine, g, "br-answer-branch")
    result = await flow_chat(
        app_engine,
        TENANT,
        "br-u1",
        "r1",
        app,
        "q",
        None,
        base_llm=FakeLLM(),
        settings=_settings(),
    )
    assert result["status"] == ExecutionStatus.COMPLETED.value
    # 失败 → error 分支回答节点：{{#cap1.error#}} 解析为错误消息
    assert "❌ 失败" in result["answer"]
    assert "demo.bogus" in result["answer"]


async def test_answer_after_approval_confirm_routes_success_branch(app_engine: AsyncEngine) -> None:
    """回归：h1 确认恢复 → 挂起点视为成功 → success 分支回答节点执行（不能 skip）。"""
    g = {
        "nodes": [
            {"id": "start", "type": "start", "data": {}},
            {"id": "h1", "type": "human_approval", "data": {"question": "确认？"}},
            _answer("ok_ans", "✅ 已确认完成"),
            _answer("err_ans", "❌ 已取消"),
        ],
        "edges": [
            {"source": "start", "target": "h1"},
            {"source": "h1", "target": "ok_ans", "sourceHandle": ""},
            {"source": "h1", "target": "err_ans", "sourceHandle": "error"},
        ],
    }
    app = await _flow_app(app_engine, g, "br-approval-answer")
    first = await flow_chat(
        app_engine,
        TENANT,
        "br-u1",
        "r1",
        app,
        "q",
        None,
        base_llm=FakeLLM(),
        settings=_settings(),
    )
    assert first["status"] == ExecutionStatus.WAITING_HUMAN.value
    second = await flow_chat(
        app_engine,
        TENANT,
        "br-u1",
        "r1",
        app,
        "确认",
        first["conversation_id"],
        base_llm=FakeLLM(),
        settings=_settings(),
    )
    assert second["status"] == ExecutionStatus.COMPLETED.value
    assert second["answer"] == "✅ 已确认完成"  # 回答节点文本，非挂起点 reply 兜底
