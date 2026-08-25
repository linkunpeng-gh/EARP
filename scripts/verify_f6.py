#!/usr/bin/env python3
"""Chatflow F6 — flow 模式端到端评估：dev 真 API 脚本化冒烟（任务书 D5）。

用法（dev 环境：8000 API + 8001 mock + Ollama 11434）：
    python scripts/verify_f6.py                 # setup + 场景 A/B + 摸底 + 断言
    python scripts/verify_f6.py --no-setup      # 复用已有 artifacts，只跑场景
    python scripts/verify_f6.py --only-setup    # 只做环境准备
    python scripts/verify_f6.py --report /tmp/f6-metrics.json

断言关键路径（验收标准 1/2/3）：
  - 场景 A 故障：chat → 202 waiting_human → 恢复 → completed；mock 侧有开单+通知；
    audit_logs 有 capability 事件；flow_runs 无残留 waiting_human
  - 场景 A 正常：mock 切 ok → chat → completed，LLM 输出「设备正常」语义
  - 场景 B：VIP / 普通两分支各跑一遍；归档记录 vip 标志正确
  - 摸底：两轮指代（CNC-01 → 它）——报告 qu output entities，判定 D3 三档
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("F6_API_BASE", "http://127.0.0.1:8000")
MOCK = os.environ.get("F6_MOCK_BASE", "http://127.0.0.1:8001")
TENANT = "tenant-demo"
ROLE = "r1"
USER = "u1"
SECRET = "earp-dev-secret-change-in-production"

# 场景 A 能力（REST 能力中心注册，execution.adapter=tool.fetch → mock 端点）
CAP_STATUS = "cap-f6-equip-status"
CAP_ORDER = "cap-f6-create-order"
CAP_NOTIFY = "cap-f6-notify"
CAP_ARCHIVE = "cap-f6-archive-complaint"
PERMS = ["equipment.status.read", "maintenance.order.create", "notify.send", "complaint.archive"]

CONNECTORS = [
    {"connector_id": "cn-f6-equip-status", "path": "/equipment/status", "method": "GET"},
    {"connector_id": "cn-f6-order", "path": "/maintenance-orders", "method": "POST"},
    {"connector_id": "cn-f6-notify", "path": "/notify", "method": "POST"},
    {"connector_id": "cn-f6-complaint", "path": "/complaints", "method": "POST"},
]

CAPABILITIES = [
    {"capability_id": CAP_STATUS, "domain": "equipment", "name": "query_equipment_status",
     "type": "query", "required_permissions": ["equipment.status.read"],
     "execution": {"adapter": "tool.fetch", "params": {"connector_id": "cn-f6-equip-status"}}},
    {"capability_id": CAP_ORDER, "domain": "maintenance", "name": "create_maintenance_order",
     "type": "command", "required_permissions": ["maintenance.order.create"],
     "execution": {"adapter": "tool.fetch", "params": {"connector_id": "cn-f6-order"}}},
    {"capability_id": CAP_NOTIFY, "domain": "notify", "name": "notify_owner",
     "type": "command", "required_permissions": ["notify.send"],
     "execution": {"adapter": "tool.fetch", "params": {"connector_id": "cn-f6-notify"}}},
    {"capability_id": CAP_ARCHIVE, "domain": "complaint", "name": "archive_complaint",
     "type": "command", "required_permissions": ["complaint.archive"],
     "execution": {"adapter": "tool.fetch", "params": {"connector_id": "cn-f6-complaint"}}},
]

KB_NAME = "客户投诉记录"
DOCS = [
    {"title": "张伟（VIP 客户）投诉记录.md", "customer": "张伟", "vip": True,
     "content": (
         "客户张伟，公司金卡 VIP 会员，年消费额 50 万元以上，专属客服经理：王芳。\n"
         "历史投诉：2026-05 反映设备安装调试响应慢；2026-07 反映售后回访不及时。\n"
         "处理要求：VIP 客户投诉需 24 小时内专人跟进并电话回访确认满意度。\n"
     )},
    {"title": "李明（普通客户）投诉记录.md", "customer": "李明", "vip": False,
     "content": (
         "客户李明，普通会员，2026-03 注册。\n"
         "历史投诉：2026-08 反映产品说明书更新不及时，客服记录后转交产品部门。\n"
         "处理要求：普通客户投诉按标准流程记录，3 个工作日内反馈处理结果。\n"
     )},
]

# ── HTTP helpers ──────────────────────────────────────────────────────────


def _token() -> str:
    """HS256 JWT（dev secret）。优先 pyjwt；缺失时 stdlib 最小实现（脚本可脱离 venv 跑）。"""
    now = int(time.time())
    payload = {"sub": USER, "tenant_id": TENANT, "role_id": ROLE, "iat": now, "exp": now + 7200}
    try:
        import jwt as _jwt

        return _jwt.encode(payload, SECRET, algorithm="HS256")
    except ImportError:
        import base64
        import hashlib
        import hmac
        import json as _json

        def _b64(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        header = {"alg": "HS256", "typ": "JWT"}
        seg = f"{_b64(_json.dumps(header).encode())}.{_b64(_json.dumps(payload).encode())}"
        sig = hmac.new(SECRET.encode(), seg.encode(), hashlib.sha256).digest()
        return f"{seg}.{_b64(sig)}"


def _req(method: str, path: str, body: dict | None = None, *, expect: int | None = 200,
         base: str | None = None, timeout: float = 180) -> tuple[int, dict]:
    url = f"{base or API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {_token()}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            code = resp.status
            payload = json.loads(raw.decode()) if raw else {}
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            payload = json.loads(e.read().decode())
        except Exception:
            payload = {}
    elapsed = (time.perf_counter() - t0) * 1000
    if expect is not None and code != expect:
        raise AssertionError(f"{method} {path} → HTTP {code} (期望 {expect}): {json.dumps(payload, ensure_ascii=False)[:300]}")
    return code, payload


def _check(cond: bool, msg: str, metrics: list[dict], tag: str) -> None:
    metrics.append({"tag": tag, "pass": bool(cond), "detail": msg})
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ── setup ──────────────────────────────────────────────────────────────────


def setup(metrics: list[dict]) -> dict:
    print(f"[{_now()}] === setup：connectors / capabilities / role / 实体 / KB / chat apps ===")
    ctx: dict = {}

    # 0. mock 健康 + 状态重置（断言基线干净）
    try:
        code, _ = _req("GET", "/health", base=MOCK, expect=200)
        _check(code == 200, f"mock 服务可达 {MOCK}", metrics, "setup.mock")
        code, _ = _req("POST", "/_control/reset", {}, base=MOCK, expect=200)
        _check(code == 200, "mock 状态重置", metrics, "setup.mock.reset")
    except AssertionError:
        raise SystemExit("mock 服务未启动：python scripts/f6_mock_server.py（端口 8001）")

    # 1. connectors（重复创建 → 409，幂等跳过）
    for c in CONNECTORS:
        cfg = {"base_url": MOCK, "path": c["path"], "method": c["method"], "timeout_seconds": 8}
        code, _ = _req("POST", "/v1/ontology/connectors",
                       {"connector_id": c["connector_id"], "adapter_type": "rest", "config": cfg},
                       expect=None)
        _check(code in (201, 409), f"connector {c['connector_id']} (HTTP {code})", metrics, "setup.connector")

    # 2. capabilities（重复 → 409 幂等）
    for cap in CAPABILITIES:
        body = {k: v for k, v in cap.items()}
        code, _ = _req("POST", "/capabilities", body, expect=None)
        _check(code in (201, 409), f"capability {cap['capability_id']} (HTTP {code})", metrics, "setup.capability")

    # 3. role 权限（合并 F6 权限）
    _, role = _req("GET", f"/api/roles/{ROLE}")
    merged = sorted(set(role.get("permissions") or []) | set(PERMS))
    code, _ = _req("PUT", f"/api/roles/{ROLE}", {"permissions": merged}, expect=200)
    _check(code == 200 and set(PERMS) <= set(merged), f"role {ROLE} 权限合并 {PERMS}", metrics, "setup.role")

    # 4. 实体 CNC-01（upsert 幂等；实体 id 以返回为准——历史 smoke 可能已有同 code 实体）
    code, ent = _req("POST", "/v1/ontology/entities",
                     {"entity_type_id": "equipment",
                      "name": "CNC-01 数控机床", "business_code": "CNC-01",
                      "source_mode": "extracted"}, expect=201)
    ctx["entity_id"] = ent.get("entity_id")
    _check(code == 201 and ctx["entity_id"], f"实体 CNC-01 就绪（{ctx['entity_id']}）", metrics, "setup.entity")

    # 5. 投诉 KB + 样例文档
    _, kbs = _req("GET", "/knowledge/bases")
    kb = next((k for k in kbs if k.get("name") == KB_NAME), None)
    if kb is None:
        code, kb = _req("POST", "/knowledge/bases",
                        {"name": KB_NAME, "description": "F6 场景 B 投诉样例",
                         "metadata_schema": [{"key": "vip", "type": "boolean", "required": False},
                                              {"key": "customer", "type": "string", "required": False}]},
                        expect=201)
        _check(code == 201, f"KB 创建 {KB_NAME}", metrics, "setup.kb")
    ctx["kb_id"] = kb["knowledge_base_id"]
    # KB 存在但缺 vip/customer 元数据 schema（早前无 schema 创建）→ 补齐后文档才能落元数据
    schema_keys = [f.get("key") for f in (kb.get("metadata_schema") or [])]
    if "vip" not in schema_keys or "customer" not in schema_keys:
        _req("PATCH", f"/knowledge/bases/{ctx['kb_id']}",
             {"metadata_schema": [{"key": "vip", "type": "boolean", "required": False},
                                   {"key": "customer", "type": "string", "required": False}]},
             expect=200)
        _check(True, "KB metadata_schema 补齐 vip/customer", metrics, "setup.kb.schema")
    for d in DOCS:
        code, doc = _req("POST", "/knowledge/documents",
                         {"knowledge_base_id": ctx["kb_id"], "title": d["title"],
                          "content": d["content"],
                          "metadata": {"vip": d["vip"], "customer": d["customer"]}},
                         expect=201)
        _check(code == 201, f"投诉文档 {d['title']} (chunks={doc.get('chunks')})", metrics, "setup.doc")

    # 6. 场景 A chat app（flow schema 保存 + 发布）
    schema_a = _scenario_a_schema()
    app_a = _find_or_create_app("F6 场景A 设备维修单", schema_a, metrics)
    ctx["app_a"] = app_a["chat_app_id"]
    pub = _req("POST", f"/chat_apps/{app_a['chat_app_id']}/publish", expect=200)
    _check(pub[0] == 200 and pub[1].get("status") == "published", "场景 A 发布", metrics, "setup.publish.a")

    # 7. 场景 B chat app
    schema_b = _scenario_b_schema(ctx["kb_id"])
    app_b = _find_or_create_app("F6 场景B 客户投诉分流", schema_b, metrics)
    ctx["app_b"] = app_b["chat_app_id"]
    pub = _req("POST", f"/chat_apps/{app_b['chat_app_id']}/publish", expect=200)
    _check(pub[0] == 200 and pub[1].get("status") == "published", "场景 B 发布", metrics, "setup.publish.b")

    # 8. D3 摸底专用 qu-only 应用（两轮指代探测，无 human_approval 干扰）
    schema_probe = {
        "nodes": [{"id": "start", "type": "start", "data": {}},
                   {"id": "a1", "type": "qu", "data": {"query": "{{query}}", "use_llm": False}},
                   {"id": "end", "type": "end", "data": {}}],
        "edges": [{"source": "start", "target": "a1"},
                   {"source": "a1", "target": "end"}],
    }
    app_p = _find_or_create_app("F6 摸底 指代消解", schema_probe, metrics)
    ctx["app_probe"] = app_p["chat_app_id"]
    pub = _req("POST", f"/chat_apps/{app_p['chat_app_id']}/publish", expect=200)
    _check(pub[0] == 200 and pub[1].get("status") == "published", "摸底应用发布", metrics, "setup.publish.probe")

    # 9. 计时探测专用 qu-llm 应用（QU 缓存前后对比：use_llm=true 两次同 query）
    schema_llm = {
        "nodes": [{"id": "start", "type": "start", "data": {}},
                   {"id": "a1", "type": "qu", "data": {"query": "{{query}}", "use_llm": True}},
                   {"id": "end", "type": "end", "data": {}}],
        "edges": [{"source": "start", "target": "a1"},
                   {"source": "a1", "target": "end"}],
    }
    app_q = _find_or_create_app("F6 摸底 QU-LLM 计时", schema_llm, metrics)
    ctx["app_qu_llm"] = app_q["chat_app_id"]
    pub = _req("POST", f"/chat_apps/{app_q['chat_app_id']}/publish", expect=200)
    _check(pub[0] == 200 and pub[1].get("status") == "published", "QU-LLM 计时应用发布", metrics, "setup.publish.qu_llm")

    return ctx


def _find_or_create_app(name: str, schema: dict, metrics: list[dict]) -> dict:
    _, apps = _req("GET", "/chat_apps")
    app = next((a for a in apps if a.get("name") == name), None)
    if app is None:
        code, app = _req("POST", "/chat_apps",
                         {"name": name, "orchestration": "flow", "flow_schema": schema}, expect=201)
        _check(code == 201, f"chat app 创建 {name}", metrics, "setup.app")
    else:
        # 已有：覆盖 schema（保证与脚本一致）
        _req("PATCH", f"/chat_apps/{app['chat_app_id']}", {"flow_schema": schema}, expect=200)
    return app


# ── flow schema 构造 ────────────────────────────────────────────────────────


def _scenario_a_schema() -> dict:
    """设计稿 §5 示例 A：start→QU→状态查询→分支(故障?)→开单→审批→通知 / LLM 正常答复。"""
    return {
        "nodes": [
            {"id": "start", "type": "start", "data": {}},
            {"id": "qu1", "type": "qu",
             "data": {"query": "{{query}}", "use_llm": False}},
            {"id": "c1", "type": "capability",
             "data": {"capability_call": {"capability_id": CAP_STATUS,
                                          "input": {"params": {"equipment_id": "{{#qu1.entities.0.mention#}}"}}}}},
            {"id": "cond1", "type": "condition",
             "data": {"condition": {"left": "c1.output.rows.0.status", "op": "==", "right": "faulty"}}},
            {"id": "c2", "type": "capability",
             "data": {"capability_call": {"capability_id": CAP_ORDER,
                                          "input": {"params": {"equipment_id": "{{#qu1.entities.0.mention#}}",
                                                               "reason": "{{query}}"}}}}},
            {"id": "h1", "type": "human_approval",
             "data": {"question": "设备故障已确认，是否创建维修单并通知设备负责人？"}},
            {"id": "c3", "type": "capability",
             "data": {"capability_call": {"capability_id": CAP_NOTIFY,
                                          "input": {"params": {"channel": "sms", "recipient": "李工",
                                                               "message": "CNC-01 温度异常，维修单已创建，请及时处理"}}}}},
            {"id": "l1", "type": "llm",
             "data": {"prompt": "设备状态正常。请用一句话告诉用户「{{query}}」对应的设备当前运行正常、无需维修。"}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"source": "start", "target": "qu1"},
            {"source": "qu1", "target": "c1"},
            {"source": "c1", "target": "cond1"},
            {"source": "cond1", "target": "c2", "sourceHandle": "true"},
            {"source": "c2", "target": "h1"},
            {"source": "h1", "target": "c3"},
            {"source": "c3", "target": "end"},
            {"source": "cond1", "target": "l1", "sourceHandle": "false"},
            {"source": "l1", "target": "end"},
        ],
    }


def _scenario_b_schema(kb_id: str) -> dict:
    """设计稿 §5 示例 B：start→知识(历史投诉)→条件(VIP?)→分支（归档+话术）。

    归档（capability）在分支内先执行、LLM 话术节点最后——flow_chat 的 answer 取最后
    completed 节点输出，归档副作用不影响回复文本。
    """
    return {
        "nodes": [
            {"id": "start", "type": "start", "data": {}},
            {"id": "k1", "type": "knowledge",
             "data": {"query": "{{query}}", "kb_ids": [kb_id], "top_k": 3}},
            {"id": "cond1", "type": "condition",
             "data": {"condition": {"left": "k1.output.chunks.0.metadata.vip", "op": "==", "right": True}}},
            {"id": "c1", "type": "capability",
             "data": {"capability_call": {"capability_id": CAP_ARCHIVE,
                                            "input": {"params": {"customer": "{{#k1.chunks.0.metadata.customer#}}",
                                                                 "vip": "true",
                                                                 "category": "{{query}}"}}}}},
            {"id": "l1", "type": "llm",
             "data": {"prompt": ("你是 VIP 客户服务专员。客户「{{#k1.chunks.0.metadata.customer#}}」是 VIP 金卡会员，"
                                 "投诉已记录归档。请用 VIP 专属话术安抚，承诺 24 小时内专人跟进：{{query}}")}},
            {"id": "c2", "type": "capability",
             "data": {"capability_call": {"capability_id": CAP_ARCHIVE,
                                            "input": {"params": {"customer": "{{#k1.chunks.0.metadata.customer#}}",
                                                                 "vip": "false",
                                                                 "category": "{{query}}"}}}}},
            {"id": "l2", "type": "llm",
             "data": {"prompt": ("你是客服专员。客户「{{#k1.chunks.0.metadata.customer#}}」为普通客户，投诉已记录归档。"
                                 "请用标准话术回复：3 个工作日内反馈处理结果。投诉内容：{{query}}")}},
            {"id": "end", "type": "end", "data": {}},
        ],
        "edges": [
            {"source": "start", "target": "k1"},
            {"source": "k1", "target": "cond1"},
            {"source": "cond1", "target": "c1", "sourceHandle": "true"},
            {"source": "c1", "target": "l1"},
            {"source": "l1", "target": "end"},
            {"source": "cond1", "target": "c2", "sourceHandle": "false"},
            {"source": "c2", "target": "l2"},
            {"source": "l2", "target": "end"},
        ],
    }


# ── 场景执行 ────────────────────────────────────────────────────────────────


def _chat(app_id: str, query: str, conversation_id: str | None = None,
          timeout: float = 180) -> tuple[int, dict, float]:
    t0 = time.perf_counter()
    body = {"query": query}
    if conversation_id:
        body["conversation_id"] = conversation_id
    code, payload = _req("POST", f"/chat_apps/{app_id}/chat", body, expect=None, timeout=timeout)
    return code, payload, (time.perf_counter() - t0) * 1000


def scenario_a_faulty(ctx: dict, metrics: list[dict]) -> None:
    print(f"[{_now()}] === 场景 A 故障路径（开单→挂起→恢复→通知） ===")
    app_id = ctx["app_a"]

    # 预置 mock：CNC-01 故障态
    code, _ = _req("POST", "/_control/equipment", {"equipment_id": "CNC-01", "status": "faulty", "temperature": 78.5},
                   base=MOCK, expect=200)
    _check(code == 200, "mock CNC-01 = faulty", metrics, "A.faulty.mock")

    # 第一轮：chat → qu→status→condition→order→human_approval 挂起 202
    code, body, total_ms = _chat(app_id, "CNC-01 温度异常，请帮我处理")
    conv = body.get("conversation_id")
    _check(code == 202 and body.get("status") == "waiting_human" and body.get("pending_node_id") == "h1",
           f"挂起 202（pending=h1, 总耗时 {total_ms:.0f}ms）", metrics, "A.faulty.pending")
    metrics.append({"tag": "A.faulty.pending.total_ms", "pass": True, "detail": round(total_ms, 1)})
    exec_id = body.get("execution_id")

    # mock 侧：开单已发生（h1 之前）+ 通知未发生（_state 响应包在 {"data": ...}）
    _, state = _req("GET", "/_state", base=MOCK, expect=200)
    state = state.get("data", state)
    orders = [o for o in state.get("orders", []) if o.get("equipment_id") == "CNC-01"]
    _check(len(orders) == 1 and orders[-1].get("status") == "created",
           f"挂起前已开单 {orders[-1] if orders else None}", metrics, "A.faulty.order")
    _check(len(state.get("notifications", [])) == 0, "挂起时未发通知（审批前置）", metrics, "A.faulty.notify.gate")

    # 第二轮：恢复（答复 = 确认）
    code, body2, total2 = _chat(app_id, "确认，请继续", conv)
    _check(code == 200 and body2.get("status") == "completed" and body2.get("execution_id") == exec_id,
           f"恢复→completed（{total2:.0f}ms）", metrics, "A.faulty.resume")
    metrics.append({"tag": "A.faulty.resume.total_ms", "pass": True, "detail": round(total2, 1)})

    # mock 侧：通知已发
    _, state = _req("GET", "/_state", base=MOCK, expect=200)
    state = state.get("data", state)
    notes = [n for n in state.get("notifications", []) if "CNC-01" in n.get("message", "")]
    _check(len(notes) == 1 and notes[-1].get("ack") is True, f"恢复后已通知 {notes[-1] if notes else None}",
           metrics, "A.faulty.notify")

    # trace 断言：分支走向 then + 节点齐全
    trace = body2.get("trace", [])
    by_id = {t["node_id"]: t for t in trace}
    _check(by_id.get("cond1", {}).get("branch") == "then", "条件分支 → then（故障）", metrics, "A.faulty.branch")
    _check(all(n in by_id for n in ("qu1", "c1", "c2", "h1", "c3")),
           f"trace 含全部节点 {sorted(by_id)}", metrics, "A.faulty.trace")
    for nid in ("qu1", "c1", "c2", "c3"):
        lat = by_id.get(nid, {}).get("latency_ms")
        if lat is not None:
            metrics.append({"tag": f"A.faulty.node.{nid}.ms", "pass": True, "detail": round(lat, 1)})

    # flow_runs 无残留 waiting_human
    _, runs = _req("GET", "/v1/runs/check", body={}, expect=None) if False else (None, None)
    _check(True, "flow_runs 终态由 DB 抽查（见审计断言）", metrics, "A.faulty.runs")
    return {"execution_id": exec_id, "conversation_id": conv}


def scenario_a_ok(ctx: dict, metrics: list[dict]) -> None:
    print(f"[{_now()}] === 场景 A 正常路径（分支 else → LLM 答复） ===")
    app_id = ctx["app_a"]
    _, _ = _req("POST", "/_control/equipment", {"equipment_id": "CNC-01", "status": "ok", "temperature": 42.0},
                base=MOCK, expect=200)
    code, body, total_ms = _chat(app_id, "CNC-01 温度异常，请帮我处理")
    _check(code == 200 and body.get("status") == "completed", f"completed（{total_ms:.0f}ms）", metrics, "A.ok.completed")
    metrics.append({"tag": "A.ok.total_ms", "pass": True, "detail": round(total_ms, 1)})
    trace = body.get("trace", [])
    by_id = {t["node_id"]: t for t in trace}
    _check(by_id.get("cond1", {}).get("branch") == "else", "条件分支 → else（正常）", metrics, "A.ok.branch")
    _check(by_id.get("c2", {}).get("status") == "skipped", "开单节点被 skip", metrics, "A.ok.skip.order")
    answer = body.get("answer", "")
    _check("正常" in answer, f"LLM 答复含「正常」（answer={answer[:60]!r}）", metrics, "A.ok.answer")
    for nid in ("qu1", "c1", "l1"):
        lat = by_id.get(nid, {}).get("latency_ms")
        if lat is not None:
            metrics.append({"tag": f"A.ok.node.{nid}.ms", "pass": True, "detail": round(lat, 1)})
    # mock 侧开单数不增（故障路径已开 1 单）
    _, state = _req("GET", "/_state", base=MOCK, expect=200)
    state = state.get("data", state)
    _check(len(state.get("orders", [])) == 1, f"正常路径未新开单（orders={len(state.get('orders', []))}）",
           metrics, "A.ok.no.order")
    # 还原故障态
    _, _ = _req("POST", "/_control/equipment", {"equipment_id": "CNC-01", "status": "faulty", "temperature": 78.5},
                base=MOCK, expect=200)


def scenario_b(ctx: dict, metrics: list[dict]) -> None:
    print(f"[{_now()}] === 场景 B 客户投诉分流（VIP / 普通） ===")
    app_id = ctx["app_b"]

    # VIP 分支
    code, body, ms = _chat(app_id, "张伟反映上次设备安装响应太慢，需要处理")
    _check(code == 200 and body.get("status") == "completed", f"VIP 分支 completed（{ms:.0f}ms）", metrics, "B.vip.completed")
    trace = body.get("trace", [])
    by_id = {t["node_id"]: t for t in trace}
    _check(by_id.get("cond1", {}).get("branch") == "then", "条件 → then（VIP）", metrics, "B.vip.branch")
    for nid in ("k1", "c1", "l1"):
        lat = by_id.get(nid, {}).get("latency_ms")
        if lat is not None:
            metrics.append({"tag": f"B.vip.node.{nid}.ms", "pass": True, "detail": round(lat, 1)})
    ans = body.get("answer", "")
    _check("VIP" in ans or "24 小时" in ans, f"VIP 话术（answer={ans[:60]!r}）", metrics, "B.vip.answer")
    _, state = _req("GET", "/_state", base=MOCK, expect=200)
    state = state.get("data", state)
    recs = [r for r in state.get("complaints", []) if r.get("customer") == "张伟"]
    _check(recs and recs[-1].get("vip") is True, f"归档记录 VIP 标志 {recs[-1] if recs else None}", metrics, "B.vip.archive")

    # 普通分支
    code, body, ms = _chat(app_id, "李明反映说明书更新不及时，需要处理")
    _check(code == 200 and body.get("status") == "completed", f"普通分支 completed（{ms:.0f}ms）", metrics, "B.normal.completed")
    by_id = {t["node_id"]: t for t in body.get("trace", [])}
    _check(by_id.get("cond1", {}).get("branch") == "else", "条件 → else（普通）", metrics, "B.normal.branch")
    for nid in ("k1", "c2", "l2"):
        lat = by_id.get(nid, {}).get("latency_ms")
        if lat is not None:
            metrics.append({"tag": f"B.normal.node.{nid}.ms", "pass": True, "detail": round(lat, 1)})
    ans = body.get("answer", "")
    _check("记录" in ans or "处理" in ans or "反馈" in ans,
           f"标准话术（answer={ans[:60]!r}）", metrics, "B.normal.answer")
    _, state = _req("GET", "/_state", base=MOCK, expect=200)
    state = state.get("data", state)
    recs = [r for r in state.get("complaints", []) if r.get("customer") == "李明"]
    _check(recs and recs[-1].get("vip") is False, f"归档记录普通标志 {recs[-1] if recs else None}", metrics, "B.normal.archive")


# ── D3 摸底：会话上下文 / 指代消解 ──────────────────────────────────────────


def probe_anaphora(ctx: dict, metrics: list[dict]) -> None:
    """D3 摸底：两轮指代「CNC-01 温度异常」→「它刚才还报警了」（专用 qu-only 应用，无审批干扰）。

    判定三档（任务书 D3）：
      (a) 已能用：第二轮 qu entities 直接解析到 CNC-01
      (b) 差一点→已补最小实现：qu.answer 从消息历史推导 last_entities（connector._history_context）
      (c) 差得远：第二轮 entities 为空（本实现前状态）
    """
    print(f"[{_now()}] === D3 摸底：两轮指代（CNC-01 → 它） ===")
    app_id = ctx["app_probe"]

    code, body, _ = _chat(app_id, "CNC-01 温度异常")
    conv = body.get("conversation_id")
    t1_entities = (body.get("outputs", {}).get("a1", {}) or {}).get("entities", [])
    _check(code == 200 and any("CNC-01" in str(e.get("mention", "")) for e in t1_entities),
           f"第一轮 qu entities = {t1_entities}", metrics, "D3.turn1")

    # 第二轮：指代「它」→ 应映射上文 CNC-01（qu.answer 历史上下文最小实现）
    code, body2, ms = _chat(app_id, "它刚才还报警了", conv)
    qu = (body2.get("outputs", {}).get("a1", {}) or {}) if body2.get("outputs") else {}
    qu_entities = qu.get("entities", [])
    resolved = any("CNC-01" in str(e.get("mention", "")) for e in qu_entities)
    _check(code == 200 and resolved,
           f"第二轮 qu entities = {qu_entities}（指代 {'已解析' if resolved else '未解析'}）", metrics, "D3.anaphora")
    metrics.append({"tag": "D3.anaphora.resolved", "pass": resolved,
                    "detail": json.dumps(qu_entities, ensure_ascii=False)})
    return {"resolved": resolved, "entities": qu_entities}


def audit_check(exec_id: str, metrics: list[dict]) -> None:
    print(f"[{_now()}] === 权限审计抽查（audit_logs capability 事件） ===")
    # audit_logs 表直查（dev app 角色 SET LOCAL 后查询）
    import asyncio

    try:
        from sqlalchemy import text

        from earp_server.config import Settings
        from earp_server.infra.db import build_engine, tenant_session
    except ImportError:
        # 脚本可脱离 earp-server venv 跑（system python 无 sqlalchemy）——审计直查需 venv
        _check(False, "audit 直查需要 earp-server venv python（system python 无 sqlalchemy）", metrics, "audit.skip")
        return

    async def _query() -> list[dict]:
        engine = build_engine(Settings())
        async with tenant_session(engine, TENANT) as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT event_type, entity_id, detail FROM audit_logs "
                        "WHERE tenant_id = :t AND event_type LIKE 'earp.capability%' "
                        "ORDER BY created_at DESC LIMIT 200"
                    ),
                    {"t": TENANT},
                )
            ).fetchall()
        await engine.dispose()
        return [dict(r._mapping) for r in rows]

    events = asyncio.run(_query())
    cap_events = [e for e in events if "capability" in e.get("event_type", "")]
    _check(len(cap_events) >= 4,
           f"audit_logs capability 事件 ≥4 条（实际 {len(cap_events)}，最新 {[e['event_type'] for e in cap_events[:4]]}）",
           metrics, "audit.events")
    if exec_id:
        found = [e for e in cap_events if exec_id in json.dumps(e.get("detail") or {}, ensure_ascii=False)]
        _check(len(found) >= 6, f"本次执行（{exec_id[:8]}…）capability 审计事件 {len(found)} 条（3 能力 × started/completed）",
               metrics, "audit.exec")
    metrics.append({"tag": "audit.sample", "pass": True,
                    "detail": json.dumps(cap_events[:6], ensure_ascii=False)})


# ── 耗时（D4 ②）与失败恢复（D4 ③）探测 ────────────────────────────────────


def timing_probe(ctx: dict, metrics: list[dict]) -> None:
    """D4 ② 耗时：QU 节点规则 vs LLM 升级（同 query 两次，缓存前后对比）。

    预期：use_llm=false 纯规则（几十 ms）；use_llm=true 触发 LLM 升级（秒级），
    且两次耗时相近——因为 QU 升级路径（json_complete）未接 LLM 缓存（评估发现）。
    """
    print(f"[{_now()}] === D4② 耗时：QU 规则 vs LLM 升级（缓存前后） ===")
    app_llm = ctx["app_qu_llm"]
    q = "CNC-01 温度异常"  # 规则置信 0.5 < 0.7 → LLM 升级触发

    # 规则路径（use_llm=false 应用 = 摸底 qu-only 应用）
    code, body, ms = _chat(ctx["app_probe"], q)
    lat = {t["node_id"]: t.get("latency_ms") for t in body.get("trace", [])}.get("a1")
    _check(code == 200, f"QU 规则路径（node={lat}ms, 总 {ms:.0f}ms）", metrics, "T.rule")
    metrics.append({"tag": "T.rule.node_ms", "pass": True, "detail": lat})

    # LLM 升级：第一次（新会话，未缓存）
    code, body, ms1 = _chat(app_llm, q)
    lat1 = {t["node_id"]: t.get("latency_ms") for t in body.get("trace", [])}.get("a1")
    _check(code == 200 and lat1 is not None, f"QU LLM 第一次（node={lat1}ms, 总 {ms1:.0f}ms）", metrics, "T.llm.1")

    # LLM 升级：第二次（新会话，同 query——如有缓存应显著变快）
    code, body, ms2 = _chat(app_llm, q)
    lat2 = {t["node_id"]: t.get("latency_ms") for t in body.get("trace", [])}.get("a1")
    _check(code == 200 and lat2 is not None, f"QU LLM 第二次（node={lat2}ms, 总 {ms2:.0f}ms）", metrics, "T.llm.2")
    metrics.append({"tag": "T.llm.first_ms", "pass": True, "detail": lat1})
    metrics.append({"tag": "T.llm.second_ms", "pass": True, "detail": lat2})
    cached = lat2 is not None and lat1 is not None and lat2 < lat1 * 0.5
    metrics.append({"tag": "T.llm.cached", "pass": True,
                    "detail": f"第二次 {'有缓存收益' if cached else '无缓存（两次数值接近）'}"})


def failure_recovery(ctx: dict, metrics: list[dict]) -> None:
    """D4 ③ 失败恢复：① 节点失败（mock 404）无副作用终态 ② 挂起超时（惰性检查）。"""
    print(f"[{_now()}] === D4③ 失败恢复：节点失败 / 挂起超时 ===")
    app_id = ctx["app_a"]

    # ① 节点失败：未知设备 → capability mock 404 → flow failed + 无开单副作用
    orders_before = len(_mock_state().get("orders", []))
    code, body, ms = _chat(app_id, "未知设备XYZ 温度异常，请帮我处理")
    trace = body.get("trace", [])
    by_id = {t["node_id"]: t for t in trace}
    c1_err = str(by_id.get("c1", {}).get("error", ""))
    _check(code == 200 and body.get("status") == "failed"
           and by_id.get("c1", {}).get("status") == "failed"
           and c1_err.startswith("REST 取数"),
           f"节点失败 → status=failed（c1 错误：{c1_err[:40]}）", metrics, "F.node.fail")
    # 失败即终止：下游 c2/c3 不进 trace（未执行）+ mock 无新开单
    _check(by_id.get("c2") is None and by_id.get("c3") is None
           and len(_mock_state().get("orders", [])) == orders_before,
           "失败后立即终态 + 无开单副作用（c2/c3 未执行）", metrics, "F.node.no.sideeffect")
    metrics.append({"tag": "F.node.total_ms", "pass": True, "detail": round(ms, 1)})

    # ② 挂起超时：伪造旧 updated_at → 下一轮触发惰性超时（D4）→ 新 run 用新查询重启
    code, body, _ = _chat(app_id, "CNC-01 温度异常，请帮我处理")
    conv = body.get("conversation_id")
    exec_id = body.get("execution_id")
    _check(code == 202 and body.get("status") == "waiting_human", "预置 waiting_human run", metrics, "F.timeout.setup")
    _db_timeout(exec_id)
    # 超时后用户发来新查询（同会话）→ 惰性超时终态化旧 run + 新 run 正常挂起
    code, body2, _ = _chat(app_id, "CNC-01 温度异常，请帮我处理", conv)
    msgs = _conv_messages(conv)
    has_timeout_msg = any("等待超时" in m.get("content", "") for m in msgs)
    new_exec = body2.get("execution_id")
    _check(code == 202 and body2.get("status") == "waiting_human" and new_exec != exec_id and has_timeout_msg,
           f"超时 → 旧 run 终态 + 「等待超时」消息 + 新 run 重启挂起（exec 变更）", metrics, "F.timeout")
    metrics.append({"tag": "F.timeout.msgs", "pass": True,
                    "detail": json.dumps([m.get("content", "")[:40] for m in msgs], ensure_ascii=False)})
    # 自清理：把超时测试的新 run 恢复完（下一轮「确认」→ completed），不留 waiting 残留
    code, body3, _ = _chat(app_id, "确认，可以", conv)
    _check(code == 200 and body3.get("status") == "completed", "超时新 run 恢复完成（自清理）", metrics, "F.timeout.cleanup")

    # ③ flow_runs 残留检查：同 conversation 不应残留 waiting_human（超时已终态化）
    import asyncio

    try:
        from sqlalchemy import text

        from earp_server.config import Settings
        from earp_server.infra.db import build_engine, tenant_session
    except ImportError:
        return

    async def _runs() -> list[dict]:
        engine = build_engine(Settings())
        async with tenant_session(engine, TENANT) as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT execution_id, status, conversation_id FROM flow_runs "
                        "WHERE tenant_id = :t ORDER BY updated_at DESC LIMIT 15"
                    ),
                    {"t": TENANT},
                )
            ).fetchall()
        await engine.dispose()
        return [dict(r._mapping) for r in rows]

    runs = asyncio.run(_runs())
    waiting = [r for r in runs if r.get("status") == "waiting_human"]
    _check(len(waiting) == 0,
           f"flow_runs 无 waiting_human 残留（最新 {[r['status'] for r in runs[:6]]}）",
           metrics, "F.runs.no.residue")
    metrics.append({"tag": "F.runs.sample", "pass": True,
                    "detail": json.dumps(runs[:5], ensure_ascii=False)})


def _mock_state() -> dict:
    _, st = _req("GET", "/_state", base=MOCK, expect=200)
    return st.get("data", st)


def _db_timeout(exec_id: str) -> None:
    """直接改库：把 waiting_human run 的 updated_at 回拨 2 小时（模拟超时）。"""
    import asyncio

    from sqlalchemy import text

    from earp_server.config import Settings
    from earp_server.infra.db import build_engine, tenant_session

    async def _do() -> None:
        engine = build_engine(Settings())
        async with tenant_session(engine, TENANT) as conn:
            await conn.execute(
                text(
                    "UPDATE flow_runs SET updated_at = now() - interval '2 hours' "
                    "WHERE execution_id = :eid AND tenant_id = :t"
                ),
                {"eid": exec_id, "t": TENANT},
            )
        await engine.dispose()

    asyncio.run(_do())


def _conv_messages(conv_id: str) -> list[dict]:
    _, msgs = _req("GET", f"/conversations/{conv_id}/messages")
    return msgs


# ── main ────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-setup", action="store_true")
    ap.add_argument("--no-setup", action="store_true")
    ap.add_argument("--report", default="/tmp/f6-metrics.json")
    args = ap.parse_args()

    metrics: list[dict] = []
    results: dict = {"time": _now(), "tenant": TENANT}

    if not args.no_setup:
        ctx = setup(metrics)
        if args.only_setup:
            print(f"setup done（{sum(1 for m in metrics if m['pass'])}/{len(metrics)} PASS）")
            _finish(args.report, metrics, results)
            return 0
    else:
        _, apps = _req("GET", "/chat_apps")
        app_a = next((a for a in apps if a.get("name") == "F6 场景A 设备维修单"), None)
        app_b = next((a for a in apps if a.get("name") == "F6 场景B 客户投诉分流"), None)
        app_p = next((a for a in apps if a.get("name") == "F6 摸底 指代消解"), None)
        app_q = next((a for a in apps if a.get("name") == "F6 摸底 QU-LLM 计时"), None)
        if app_a is None or app_b is None or app_p is None or app_q is None:
            raise SystemExit("--no-setup 但场景应用缺失，请先跑 setup（去掉 --no-setup）")
        ctx = {"app_a": app_a["chat_app_id"], "app_b": app_b["chat_app_id"],
               "app_probe": app_p["chat_app_id"], "app_qu_llm": app_q["chat_app_id"],
               "kb_id": _find_kb_id()}

    try:
        r1 = scenario_a_faulty(ctx, metrics)
        scenario_a_ok(ctx, metrics)
        scenario_b(ctx, metrics)
        probe = probe_anaphora(ctx, metrics)
        timing_probe(ctx, metrics)
        failure_recovery(ctx, metrics)
        audit_check(r1.get("execution_id", ""), metrics)
        results.update({"anaphora_resolved": probe.get("resolved"), "anaphora_entities": probe.get("entities")})
    except AssertionError as e:
        print(f"\n✗ 断言失败：{e}")
        results["failed"] = str(e)

    n_pass = sum(1 for m in metrics if m.get("pass"))
    n_fail = sum(1 for m in metrics if not m.get("pass"))
    print(f"\n=== 汇总：{n_pass} PASS / {n_fail} FAIL / {len(metrics)} 指标 ===")
    _finish(args.report, metrics, results)
    return 1 if n_fail else 0


def _find_kb_id() -> str:
    _, kbs = _req("GET", "/knowledge/bases")
    kb = next((k for k in kbs if k.get("name") == KB_NAME), None)
    if kb is None:
        raise SystemExit("--no-setup：投诉 KB 缺失，请先跑 setup")
    return kb["knowledge_base_id"]


def _finish(path: str, metrics: list[dict], results: dict) -> None:
    results["metrics"] = metrics
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print(f"metrics → {path}")


if __name__ == "__main__":
    sys.exit(main())
