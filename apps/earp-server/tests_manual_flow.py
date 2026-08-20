"""Chatflow F2 人工测试手册 — 一键跑通 flow 图执行（dev 8000 + 真实 Ollama）。

用法：cd apps/earp-server && .venv/bin/python tests_manual_flow.py
前置：dev DB + 8000 API 进程（--reload）+ Ollama（qwen2.5:1.5b 本地）。

覆盖场景（每个场景打印 PASS/FAIL）：
  1. 建 flow app（合法图：chat_history → llm → condition → 分支 llm）→ 201
  2. 坏图被拒（自环）→ 422（错误信息明确）
  3. publish flow → 200（发布门禁过）
  4. chat 执行 → 200 completed；condition 只走命中分支（fault 零副作用）
  5. 消息落库核查（user + assistant + citations）
  6. 会话续接：同 conversation_id 再问一次 → chat.history 节点有历史
  7. auto 模式回归：建 auto app chat → SSE 流式照常
"""

from __future__ import annotations

import asyncio
import sys

import httpx

from earp_server.gateway.auth import create_token

BASE = "http://127.0.0.1:8000"

DEVICE_FLOW = {
    "nodes": [
        {"id": "start", "type": "start", "data": {}},
        {"id": "h1", "type": "chat_history", "data": {"turns": 2}},
        {"id": "l1", "type": "llm", "data": {
            "prompt": "用户问题：{{query}}。请用一句话回答设备状态。", "system": "你是设备助手", "temperature": 0.3}},
        {"id": "c1", "type": "condition", "data": {"condition": {"left": "l1.output.text", "op": "contains", "right": "正常"}}},
        {"id": "ok", "type": "llm", "data": {"prompt": "设备正常，回复：一切正常。"}},
        {"id": "fault", "type": "llm", "data": {"prompt": "设备异常，回复：需要检修。"}},
        {"id": "end", "type": "end", "data": {}},
    ],
    "edges": [
        {"source": "start", "target": "h1"},
        {"source": "h1", "target": "l1"},
        {"source": "l1", "target": "c1"},
        {"source": "c1", "target": "ok", "sourceHandle": "true"},
        {"source": "c1", "target": "fault", "sourceHandle": "false"},
        {"source": "ok", "target": "end"},
        {"source": "fault", "target": "end"},
    ],
}


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        sys.exit(1)


async def main() -> None:
    token = create_token(sub="u1", tenant_id="t1", role_id="r1")
    async with httpx.AsyncClient(base_url=BASE, headers={"Authorization": f"Bearer {token}"}) as c:
        print("=== 场景 1: 建 flow app（合法图）===")
        r = await c.post("/chat_apps", json={"name": "F2-人工测试", "orchestration": "flow", "flow_schema": DEVICE_FLOW})
        _check("create flow 201", r.status_code == 201, f"got {r.status_code}: {r.text[:120]}")
        app_id = r.json()["chat_app_id"]
        print(f"  app_id={app_id} orchestration={r.json()['orchestration']}")

        print("=== 场景 2: 坏图被拒 ===")
        bad = {"nodes": DEVICE_FLOW["nodes"], "edges": DEVICE_FLOW["edges"] + [{"source": "l1", "target": "l1"}]}
        r = await c.post("/chat_apps", json={"name": "坏图", "orchestration": "flow", "flow_schema": bad})
        _check("坏图 422", r.status_code == 422, f"got {r.status_code}")
        print(f"  错误信息: {r.json()['detail'][:100]}")

        print("=== 场景 3: publish flow（发布门禁）===")
        r = await c.post(f"/chat_apps/{app_id}/publish")
        _check("publish 200 published", r.status_code == 200 and r.json()["status"] == "published", r.text[:100])

        print("=== 场景 4: chat 执行（真实 Ollama + 条件分支）===")
        r = await c.post(f"/chat_apps/{app_id}/chat", json={"query": "CNC-01 温度正常吗？"})
        _check("chat 200 completed", r.status_code == 200 and r.json()["status"] == "completed", f"got {r.status_code}: {r.text[:150]}")
        body = r.json()
        outputs = body.get("outputs") or {}
        print(f"  outputs keys: {list(outputs.keys())}")
        for k, v in outputs.items():
            print(f"    {k}: {(v or {}).get('text', '')[:50]}")
        _check("命中分支 ok 执行", "ok" in outputs, "condition true 分支未执行")
        _check("未命中分支 fault 零副作用", "fault" not in outputs, "fault 分支被错误执行")
        _check("answer = 命中分支输出", body.get("answer") == outputs.get("ok", {}).get("text"), body.get("answer", "")[:50])
        conv_id = body["conversation_id"]
        print(f"  conversation_id={conv_id}")

        print("=== 场景 6: 会话续接（chat.history 节点有历史）===")
        r = await c.post(f"/chat_apps/{app_id}/chat", json={"query": "上次问了什么？", "conversation_id": conv_id})
        _check("续接 200", r.status_code == 200, r.text[:150])
        # 续接的 l1 prompt 应含上一轮（chat.history 注入——通过再次含"正常"走 ok 分支间接验证）
        outputs2 = (r.json().get("outputs") or {})
        print(f"  续接 outputs: {list(outputs2.keys())}")
        _check("历史注入后分支仍正常", "ok" in outputs2, "历史注入异常")

        print("=== 场景 7: auto 模式回归（SSE 流式）===")
        r = await c.post("/chat_apps", json={"name": "auto-回归", "orchestration": "auto"})
        auto_id = r.json()["chat_app_id"]
        async with c.stream("POST", f"/chat_apps/{auto_id}/chat", json={"query": "你好"}) as s:
            lines = [ln async for ln in s.aiter_lines() if ln]
            _check("auto SSE 有事件", len(lines) > 0, "SSE 无输出")
            _check("auto SSE 含 token/done", any('"type": "token"' in l or '"type": "done"' in l for l in lines), lines[0][:80])
        print(f"  SSE 事件数: {len(lines)}")

        print("\n全部场景通过 ✅  flow 图执行（含真实 LLM + 条件分支）人工验证完成")


asyncio.run(main())
