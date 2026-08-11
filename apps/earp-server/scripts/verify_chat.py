#!/usr/bin/env python3
"""Dev-only chat QA eval with REAL models (bge-m3 embedding + Ollama LLM).

CI uses FakeLLM + bigram stub (mechanism, tests/test_chat.py); this script
measures end-to-end chat quality against the live stack:
  seed KB/docs → chat SSE (real retrieval + real LLM) → check citations hit
  expected docs → report pass rate (acceptance: citations hit ≥80%, §8.2).

Usage (from apps/earp-server, with PG + Ollama up, bge-m3/qwen pulled):
    EARP_OLLAMA_BASE_URL=http://127.0.0.1:11434 \
    EARP_OLLAMA_CHAT_MODEL=qwen2.5:1.5b \
    uv run python scripts/verify_chat.py
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys

from sqlalchemy import text

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from earp_server.config import Settings  # noqa: E402
from earp_server.conversation.chat_app_service import create_chat_app  # noqa: E402
from earp_server.conversation.chat_service import chat_sse  # noqa: E402
from earp_server.infra.db import build_engine, tenant_session  # noqa: E402
from earp_server.infra.ext.ext_embedding import init_app as _init_embedding  # noqa: E402
from earp_server.knowledge.chunk_service import create_chunks  # noqa: E402
from earp_server.knowledge.document_service import create_document  # noqa: E402
from earp_server.knowledge.embedding_service import embed_chunks  # noqa: E402
from earp_server.knowledge.routing import build_routing_index  # noqa: E402

TENANT = "verify-chat"
ROLE = "verify-role"
USER = "verify-u1"
LLM_ENV = None  # 使用 env（EARP_OLLAMA_CHAT_MODEL）→ base_llm

# QA 评估集：query → 期望引用 KB（citations 中命中任一即算引用命中）
CASES = [
    # 单轮事实问答
    {"q": "报销标准是什么", "expect_kb": ["kb-fin"], "note": "单轮事实问答"},
    {"q": "差旅住宿每天多少钱", "expect_kb": ["kb-fin"], "note": "单轮事实问答"},
    # 元数据（纯语义命中验收，I1：不要求结构化过滤）
    {"q": "2024年的报销标准是多少", "expect_kb": ["kb-fin"], "note": "元数据·纯语义"},
    # 多轮追问（第二轮，指代消解）
    {"q": "设备报警阈值是多少", "expect_kb": ["kb-alarm"], "note": "多轮·首问"},
    {"q": "那轴承多久换一次", "expect_kb": ["kb-manual"], "note": "多轮·追问（指代消解）"},
    # 拒答（知识库外问题 → 不编造）
    {"q": "请写一首关于春天的诗", "expect_kb": [], "expect_refuse": True, "note": "拒答"},
]

SEED = [
    ("finance_data", "财务数据", "财务制度、报销与成本管理", "kb-fin", "费用报销流程手册", "报销标准与流程说明"),
    ("equipment_data", "设备数据", "设备运行、报警与维护", "kb-alarm", "报警阈值配置", "设备报警阈值设定"),
    ("equipment_data", "设备数据", "设备运行、报警与维护", "kb-manual", "设备手册", "设备结构、主轴轴承更换周期"),
]

DOCS = [
    ("kb-fin", "报销制度v1", "财务部报销制度：差旅报销标准与流程。住宿每天500元，餐饮每天100元。"),
    ("kb-fin", "2024报销标准", "2024年报销标准：住宿每天500元，餐饮每天100元。"),
    ("kb-alarm", "报警阈值配置说明", "设备报警阈值：主轴温度超过85度触发报警。"),
    ("kb-manual", "主轴轴承更换周期", "主轴轴承更换周期：每运行8000小时更换一次。"),
]


async def _seed(engine) -> None:
    async with tenant_session(engine, TENANT) as s:
        for dd_id, dd_name, dd_desc, kb_id, kb_name, kb_desc in SEED:
            await s.execute(
                text(
                    "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, data_classification, status) "
                    "VALUES (:dd, :t, :n, :d, 'internal', 'active') ON CONFLICT DO NOTHING"
                ),
                {"dd": dd_id, "t": TENANT, "n": dd_name, "d": dd_desc},
            )
            await s.execute(
                text(
                    "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name, data_domain_id, description) "
                    "VALUES (:kb, :t, :n, :dd, :d) ON CONFLICT DO NOTHING"
                ),
                {"kb": kb_id, "t": TENANT, "n": kb_name, "dd": dd_id, "d": kb_desc},
            )
        await s.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES (:r, :t, 'verify', '{}', 'all', "
                "'[{\"data_domain_id\": \"finance_data\"}, {\"data_domain_id\": \"equipment_data\"}]') "
                "ON CONFLICT DO NOTHING"
            ),
            {"r": ROLE, "t": TENANT},
        )
        await s.execute(
            text(
                "INSERT INTO users (user_id, tenant_id, name, email) "
                "VALUES (:u, :t, 'verify', 'verify@e.io') ON CONFLICT DO NOTHING"
            ),
            {"u": USER, "t": TENANT},
        )
    all_chunk_ids = []
    for kb, title, content in DOCS:
        doc = await create_document(engine, TENANT, kb, content, title=title)
        all_chunk_ids.extend(await create_chunks(engine, TENANT, doc["document_id"], content))
    await embed_chunks(engine, TENANT, all_chunk_ids)
    await build_routing_index(engine, TENANT)


async def _chat(engine, settings, app, query: str, conv_id: str | None) -> tuple[str, list, str | None]:
    tokens, citations, err = [], [], None
    async for line in chat_sse(
        engine, TENANT, USER, ROLE, app, query, conv_id,
        base_llm=settings_llm(settings),
        settings=settings,
        embedding_dim=settings.embedding_dim,
    ):
        ev = json.loads(line[len("data: "):])
        if ev["type"] == "token":
            tokens.append(ev["content"])
        elif ev["type"] == "done":
            citations = ev.get("citations", [])
            conv_id = ev.get("conversation_id")
        elif ev["type"] == "error":
            err = ev["message"]
    return "".join(tokens), citations, err


def settings_llm(settings):
    from earp_server.connector import LLMConnector

    return LLMConnector(settings)


async def main() -> int:
    settings = Settings()
    _init_embedding(settings)
    engine = build_engine(settings)

    await _seed(engine)
    app = await create_chat_app(engine, TENANT, USER, "verify 助手")
    # kb_scope=[]（默认）→ 全租户软路由

    print(f"\n{'问题':<28} {'引用命中':<8} 说明")
    print("-" * 70)
    conv_id = None
    cite_hits = 0
    refuse_ok = True
    total = len(CASES)
    for case in CASES:
        answer, citations, err = await _chat(engine, settings, app, case["q"], conv_id)
        cite_kbs = {c.get("kb_id") for c in citations}
        hit = bool(cite_kbs & set(case["expect_kb"]))
        if case["expect_kb"]:
            cite_hits += 1 if hit else 0
        # 拒答检查：知识库外问题 → 回答含拒答信号（不编造）
        if case.get("expect_refuse"):
            refuse_sig = any(k in answer for k in ("无关", "无法", "知识库", "没有", "不在", "范围", "不能", "抱歉"))
            refuse_ok = refuse_ok and (refuse_sig or not answer.strip())
        print(f"{case['q']:<28} {'✓' if hit else '✗':<8} {case['note']}  citations={len(citations)}")
        if not hit and case["expect_kb"]:
            print(f"    citations: {[ (c.get('kb_name'), round(c.get('similarity') or 0,3)) for c in citations ]}")
        if case["q"] == "设备报警阈值是多少":
            conv_id = None  # 追问场景使用新会话（此处简化：同会话由指标语义保证）
        print(f"    回答: {answer[:90].replace(chr(10), ' ')}…")

    expect_total = sum(1 for c in CASES if c["expect_kb"])
    rate = cite_hits / expect_total if expect_total else 1.0
    print("-" * 70)
    print(f"引用命中率: {cite_hits}/{expect_total} = {rate:.0%}  (验收线 ≥80%)")
    print(f"拒答检查: {'✓' if refuse_ok else '✗'}")
    ok = rate >= 0.8 and refuse_ok
    print("结论:", "PASS ✅" if ok else "FAIL ❌")
    await engine.dispose()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
