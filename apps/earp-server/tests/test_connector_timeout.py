"""T2 — connector LLM 调用超时根治（2026-08-18 补记）。

根因：json_complete 默认 120s / llm 跑分 111 例 × 超时累积可挂数小时。
决策 D3：调用级显式超时（默认 30s），超时回落（json_complete → None / plan → ConnectorError），
schema 合规不破；流式 chat_stream 保持 300s（流式合理，不在此列）。

用真实 TCP 滞留服务器验证超时机制生效（httpx MockTransport 不经过网络层，
handler 内 sleep 不受 timeout 约束——必须真 socket）。
"""

from __future__ import annotations

import asyncio
import inspect
import time

import httpx
import pytest

from earp_server.config import Settings
from earp_server.connector import ConnectorError, LLMConnector


async def _stall_server() -> tuple[asyncio.AbstractServer, int, asyncio.Event]:
    """接受连接但永不响应的 TCP 服务器（客户端 read timeout 触发）。

    返回 (server, port, stop_event)——teardown 时先 set stop 让 handler 退出，
    否则 wait_closed() 会等永不返回的 handler 挂死。
    """
    stop = asyncio.Event()

    async def _stall(_reader, _writer) -> None:
        await stop.wait()  # 保持连接打开，直到 teardown

    server = await asyncio.start_server(_stall, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port, stop


async def _stall_cleanup(server: asyncio.AbstractServer, stop: asyncio.Event) -> None:
    stop.set()
    server.close()
    # 注意：不 await wait_closed()——Python 3.12 下会等 keep-alive 连接全部回收
    # （httpx 客户端已关闭但连接仍处 closing 态），导致 teardown 挂死；close() 已够，
    # 事件循环 teardown 会回收剩余任务。
    await asyncio.sleep(0)


def test_json_complete_default_timeout_is_30s() -> None:
    sig = inspect.signature(LLMConnector.json_complete)
    assert sig.parameters["timeout"].default == 30


def test_plan_default_timeout_is_30s() -> None:
    sig = inspect.signature(LLMConnector.plan)
    assert sig.parameters["timeout"].default == 30


async def test_json_complete_hanging_upstream_returns_none_within_timeout() -> None:
    """上游挂起 → 调用级超时回落 None，不无限阻塞（曾挂一天根因闭环）。"""
    server, port, stop = await _stall_server()
    try:
        conn = LLMConnector(Settings(ollama_base_url=f"http://127.0.0.1:{port}"))
        start = time.monotonic()
        out = await conn.json_complete("系统提示", "用户查询", timeout=1)
        elapsed = time.monotonic() - start
        assert out is None
        assert elapsed < 5, f"timeout 未生效: {elapsed:.1f}s"
    finally:
        await _stall_cleanup(server, stop)


async def test_plan_hanging_upstream_raises_within_timeout() -> None:
    """plan 路径同样受调用级超时约束（挂起 → ConnectorError，调用方回落规则规划器）。"""
    server, port, stop = await _stall_server()
    try:
        conn = LLMConnector(Settings(ollama_base_url=f"http://127.0.0.1:{port}"))
        start = time.monotonic()
        with pytest.raises(ConnectorError):
            await conn.plan("用户意图", timeout=1)
        elapsed = time.monotonic() - start
        assert elapsed < 5, f"timeout 未生效: {elapsed:.1f}s"
    finally:
        await _stall_cleanup(server, stop)


def _ok_handler(request: httpx.Request) -> httpx.Response:
    # ollama /api/chat JSON 响应：{"message": {"content": "..."}}
    return httpx.Response(
        200,
        json={"message": {"content": '{"description": "财务数据", "ok": true}'}},
    )


async def test_json_complete_success_path() -> None:
    """正常路径不回归：MockTransport 快速返回 JSON → dict。"""
    conn = LLMConnector(Settings(), transport=httpx.MockTransport(_ok_handler))
    out = await conn.json_complete("sys", "user", timeout=1)
    assert out == {"description": "财务数据", "ok": True}


async def test_json_complete_non_json_falls_back_none() -> None:
    """非 JSON 响应 → None（调用方回落），不抛异常（既有语义保持）。"""

    def _bad_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "not json at all"}})

    conn = LLMConnector(Settings(), transport=httpx.MockTransport(_bad_handler))
    out = await conn.json_complete("sys", "user", timeout=1)
    assert out is None


# ── F7 (Task 1 D1): json_complete 接 LLM 缓存 ─────────────────────────────────


class _FakeCache:
    """内存版 LLMCache 替身：记录 get/set，不依赖 Redis。"""

    def __init__(self) -> None:
        self.store: dict = {}
        self.gets = 0

    async def get(self, model: str, key: str):
        self.gets += 1
        return self.store.get(key)

    async def set(self, model: str, key: str, value) -> None:
        self.store[key] = value


async def test_json_complete_cache_hit_skips_llm_call() -> None:
    """F7 (Task 1): 同 messages 第二次 json_complete 命中缓存 → 零 HTTP 调用。"""
    calls: list[int] = []

    def _counting_handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"message": {"content": '{"intent": "FACT"}'}})

    conn = LLMConnector(Settings(), transport=httpx.MockTransport(_counting_handler))
    conn.cache = _FakeCache()
    r1 = await conn.json_complete("sys", "同一条提示", timeout=1)
    r2 = await conn.json_complete("sys", "同一条提示", timeout=1)
    assert r1 == {"intent": "FACT"}
    assert r2 == {"intent": "FACT"}
    assert len(calls) == 1  # 第二次命中缓存，未再调 LLM（冷启动重复全量调用消除）
    # 不同 prompt → 缓存键不同 → miss 再调
    r3 = await conn.json_complete("sys", "另一条提示", timeout=1)
    assert r3 == {"intent": "FACT"}
    assert len(calls) == 2


async def test_json_complete_failure_not_cached() -> None:
    """F7 (Task 1): 失败/非 JSON 不写缓存——瞬时故障不毒化 TTL 缓存（风险 1）。"""
    calls: list[int] = []

    def _fail_then_ok(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, json={"message": {"content": "bad json"}})
        return httpx.Response(200, json={"message": {"content": '{"intent": "FACT"}'}})

    conn = LLMConnector(Settings(), transport=httpx.MockTransport(_fail_then_ok))
    conn.cache = _FakeCache()
    assert await conn.json_complete("sys", "p", timeout=1) is None
    assert await conn.json_complete("sys", "p", timeout=1) == {"intent": "FACT"}
    assert len(calls) == 2  # 失败未缓存 → 第二次仍重试调用（不会命中「失败」）
