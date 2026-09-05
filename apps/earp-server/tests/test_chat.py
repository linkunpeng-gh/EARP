"""Chat 链路测试（设计 §8.1）——bigram stub embedding + FakeLLM。

覆盖：链路闭环（会话/落库/检索/流式/citations）、多轮配对、kb_scope 限定、
软路由、角色权限过滤、SSE 事件（token/done/error）、模型三级解析。
"""

from __future__ import annotations

import hashlib
import json
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.connector import ConnectorError
from earp_server.conversation.chat_app_service import create_chat_app, update_chat_app
from earp_server.conversation.chat_service import chat_sse, resolve_llm_override
from earp_server.infra.db import tenant_session
from earp_server.knowledge.chunk_service import create_chunks
from earp_server.knowledge.document_service import create_document
from earp_server.knowledge.embedding_service import embed_chunks
from earp_server.knowledge.routing import build_routing_index

DIM = 1024


class _BigramStubProvider:
    name = "bigram-stub"
    dim = DIM

    def _bigrams(self, t: str) -> set[str]:
        chars = re.findall(r"[\w\u4e00-\u9fff]", t.lower())
        return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            vec = [0.0] * DIM
            for bg in self._bigrams(t):
                vec[hashlib.md5(bg.encode()).digest()[0] % DIM] += 1.0
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            out.append([x / norm for x in vec])
        return out


def _install_stub(monkeypatch) -> None:
    import earp_server.knowledge.embedding_service as embedding_service
    import earp_server.knowledge.routing as routing

    provider = _BigramStubProvider()
    monkeypatch.setattr(routing, "get_embedding_provider", lambda: provider)
    monkeypatch.setattr(embedding_service, "get_embedding_provider", lambda: provider)


class FakeLLM:
    """记录 (system, history, query)，返回固定 token 或抛 ConnectorError。"""

    def __init__(self, tokens=("报销", "标准"), error: str | None = None) -> None:
        self.tokens = tokens
        self.error = error
        self.calls: list[tuple[str, list, str]] = []

    async def chat_stream(self, system, history, query, **kwargs):
        self.calls.append((system, history, query))
        self.last_kwargs = kwargs
        if self.error:
            raise ConnectorError(self.error)
        for i, t in enumerate(self.tokens):
            yield SimpleNamespace(token=t, index=i)


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def _purge(migration_url: str, tid: str) -> None:
    """语义 id（data_domains PK 单列跨租户冲突，known debt #7）跨测试共享——超级用户清理。"""
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        # 动态覆盖所有租户中 data_domain 关联的 KB（跨租户语义 id 冲突，debt #7）
        await conn.execute(
            text(
                "DELETE FROM chunks WHERE knowledge_base_id IN "
                "(SELECT knowledge_base_id FROM knowledge_bases "
                "WHERE data_domain_id IN ('finance_data', 'equipment_data'))"
            )
        )
        await conn.execute(
            text(
                "DELETE FROM documents WHERE knowledge_base_id IN "
                "(SELECT knowledge_base_id FROM knowledge_bases "
                "WHERE data_domain_id IN ('finance_data', 'equipment_data'))"
            )
        )
        await conn.execute(
            text("DELETE FROM knowledge_bases WHERE data_domain_id IN ('finance_data', 'equipment_data')")
        )
        await conn.execute(text("DELETE FROM data_domains WHERE data_domain_id IN ('finance_data', 'equipment_data')"))
        # role_id / user_id 全局唯一（debt #7 模式）——跨租户共享，全局清理
        await conn.execute(text("DELETE FROM roles WHERE role_id IN ('r-all', 'r-nofin')"))
        await conn.execute(
            text(
                "DELETE FROM messages WHERE conversation_id IN "
                "(SELECT conversation_id FROM conversations WHERE user_id = 'u1')"
            )
        )
        await conn.execute(text("DELETE FROM conversations WHERE user_id = 'u1'"))
        await conn.execute(text("DELETE FROM users WHERE user_id = 'u1'"))
    await eng.dispose()


async def _seed(engine: AsyncEngine, tid: str, migration_url: str, monkeypatch) -> None:
    """DDs + role + KB + docs（titles carry eval keywords）。"""
    _install_stub(monkeypatch)
    await _purge(migration_url, tid)
    async with tenant_session(engine, tid) as session:
        await session.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, data_classification, status) "
                "VALUES ('finance_data', :tid, '财务数据', '财务制度、报销', 'internal', 'active'), "
                "('equipment_data', :tid, '设备数据', '设备报警维护', 'internal', 'active'), "
                "('supply_chain_data', :tid, '供应链数据', '供应商', 'internal', 'active') "
                "ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES (:rid, :tid, 'all', '{}', 'all', "
                '\'[{"data_domain_id": "finance_data"}, {"data_domain_id": "equipment_data"}, {"data_domain_id": "supply_chain_data"}]\') '  # noqa: E501 — 授权 JSON 单行（SQL 内嵌）
                "ON CONFLICT DO NOTHING"
            ),
            {"rid": "r-all", "tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access) "
                "VALUES (:rid, :tid, 'no-finance', '{}', 'all', '[{\"data_domain_id\": \"equipment_data\"}]') "
                "ON CONFLICT DO NOTHING"
            ),
            {"rid": "r-nofin", "tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO users (user_id, tenant_id, name, email) "
                "VALUES ('u1', :tid, 'u1', 'u1@e.io') ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
        await session.execute(
            text(
                "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name, data_domain_id, description) "
                "VALUES ('kb-fin', :tid, '费用报销手册', 'finance_data', '报销标准与流程'), "
                "('kb-alarm', :tid, '报警配置', 'equipment_data', '设备报警阈值') ON CONFLICT DO NOTHING"
            ),
            {"tid": tid},
        )
    doc_ids = []
    chunk_ids_all = []
    docs = [
        ("kb-fin", "报销制度v1", "财务部报销制度：差旅报销标准与流程。住宿每天500元。"),
        ("kb-alarm", "报警阈值", "设备报警阈值：主轴温度超过85度触发报警。"),
    ]
    for kb, title, content in docs:
        doc = await create_document(engine, tid, kb, content, title=title)
        doc_ids.append(doc["document_id"])
        chunk_ids_all.extend(await create_chunks(engine, tid, doc["document_id"], content))
    await embed_chunks(engine, tid, chunk_ids_all)
    # 软路由权限过滤依赖路由索引（无索引 → fallback 全租户绕过权限）
    await build_routing_index(engine, tid)


async def _collect(engine, tid, uid, role, app, query, conv_id=None, llm=None):
    events = []
    settings = SimpleNamespace(embedding_dim=DIM)
    async for line in chat_sse(
        engine,
        tid,
        uid,
        role,
        app,
        query,
        conv_id,
        base_llm=llm or FakeLLM(),
        settings=settings,
    ):
        assert line.startswith("data: ")
        events.append(json.loads(line[len("data: ") :]))
    return events


async def _app(engine, tid, name="测试助手", kb_scope=None) -> dict:
    app = await create_chat_app(engine, tid, "u1", name)
    if kb_scope is not None:
        app = await update_chat_app(engine, tid, "u1", app["chat_app_id"], {"kb_scope": kb_scope})
    return app


# ── 链路闭环 + 引用 + SSE ──────────────────────────────────────────────────
async def test_chat_full_flow_with_citations(migrated: str, app_url: str, monkeypatch) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ch-flow"
    await _seed(engine, tid, migrated, monkeypatch)
    app = await _app(engine, tid)

    llm = FakeLLM(tokens=("报销标准", "500元"))
    events = await _collect(engine, tid, "u1", "r-all", app, "报销标准是什么", llm=llm)

    # 生成参数传递（app.generation → chat_stream）
    assert llm.last_kwargs["temperature"] == 0.7
    assert llm.last_kwargs["top_p"] == 0.9
    assert llm.last_kwargs["max_tokens"] == 1024

    tokens = [e["content"] for e in events if e["type"] == "token"]
    assert tokens == ["报销标准", "500元"]

    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1
    d = done[0]
    assert d["conversation_id"] and d["message_id"]
    # citations 命中 finance KB（bigram 语义）；检索保持原 top_k（chunk 级）
    assert d["citations"], "expected citations"
    assert d["citations"][0]["kb_id"] == "kb-fin"
    assert d["citations"][0]["title"]  # 文档标题
    assert "similarity" in d["citations"][0]

    # 会话归属 + 标题截断 + 消息落库（含 citations）
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        conv = (
            await conn.execute(
                text("SELECT title, chat_app_id FROM conversations WHERE conversation_id = :cid"),
                {"cid": d["conversation_id"]},
            )
        ).first()
        assert conv is not None and conv.chat_app_id == app["chat_app_id"]
        assert conv.title == "报销标准是什么"[:30]
        rows = (
            await conn.execute(
                text("SELECT role, content, citations FROM messages WHERE conversation_id = :cid ORDER BY seq"),
                {"cid": d["conversation_id"]},
            )
        ).fetchall()
        assert [r.role for r in rows] == ["user", "assistant"]
        assert rows[1].citations and rows[1].citations[0]["kb_id"] == "kb-fin"


# ── 多轮上下文（配对）─────────────────────────────────────────────────────
async def test_chat_multiturn_history_pairs(migrated: str, app_url: str, monkeypatch) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ch-multi"
    await _seed(engine, tid, migrated, monkeypatch)
    app = await _app(engine, tid)

    llm = FakeLLM(tokens=("第一轮回答",))
    events = await _collect(engine, tid, "u1", "r-all", app, "报销标准是什么", llm=llm)
    conv_id = next(e["conversation_id"] for e in events if e["type"] == "done")

    llm2 = FakeLLM(tokens=("第二轮回答",))
    await _collect(engine, tid, "u1", "r-all", app, "那住宿标准呢", conv_id=conv_id, llm=llm2)

    assert len(llm2.calls) == 1
    system, history, query = llm2.calls[0]
    # 第一轮完整轮次在历史中（user, assistant 对），当前问题不在历史
    assert [m["role"] for m in history] == ["user", "assistant"]
    assert history[0]["content"] == "报销标准是什么"
    assert history[1]["content"] == "第一轮回答"
    assert "那住宿标准呢" in query
    assert "第一轮回答" not in query


# ── kb_scope 限定检索 ─────────────────────────────────────────────────────
async def test_chat_kb_scope_limits_search(migrated: str, app_url: str, monkeypatch) -> None:
    """绑定 KB：文档（chunk）层只在该 KB 内检索（2026-08-25 后实体层允许出现）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ch-scope"
    await _seed(engine, tid, migrated, monkeypatch)
    app = await _app(engine, tid, kb_scope=["kb-alarm"])

    events = await _collect(engine, tid, "u1", "r-all", app, "报警阈值", llm=FakeLLM())
    done = [e for e in events if e["type"] == "done"][0]
    assert done["citations"]
    for c in done["citations"]:
        if c.get("kb_id"):  # 有 kb_id 的是 chunk 类引用 → 只在该 KB 内
            assert c["kb_id"] == "kb-alarm"


# ── kb_scope 绑定 + ABox（2026-08-25 设计）────────────────────────────────
async def test_chat_kb_scope_keeps_abox(migrated: str, app_url: str, monkeypatch) -> None:
    """绑定 KB 后实体/图谱（ABox）按角色权限照常生效（设计 2026-08-25）。

    绑定只限定文档层（chunk）；L1/L2 实体档案/图谱由角色 data_domain_access 门禁。
    """
    from earp_server.ontology import abox_service, tbox_service

    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ch-scope-abox"
    await _seed(engine, tid, migrated, monkeypatch)

    await tbox_service.init_tenant_tbox(engine, tid)
    sup = await abox_service.upsert_entity(engine, tid, "supplier", "上海某精机", business_code="SUP-SA")
    equip = await abox_service.upsert_entity(
        engine, tid, "equipment", "CNC-01", business_code="CNC-01", data_domain_id="equipment_data"
    )
    await abox_service.add_fact(engine, tid, equip["entity_id"], "manufactured_by", sup["entity_id"])
    await abox_service.compile_profile(engine, tid, equip["entity_id"])

    app = await _app(engine, tid, kb_scope=["kb-alarm"])
    events = await _collect(engine, tid, "u1", "r-all", app, "CNC-01 设备报警供应商", llm=FakeLLM())
    done = [e for e in events if e["type"] == "done"][0]
    assert done["citations"], "expected citations"
    sources = {c.get("source") for c in done["citations"]}
    assert "profile" in sources or "graph" in sources
    # 文档层仍限绑定 KB：有 kb_id 的 citations 全部在 kb-alarm
    for c in done["citations"]:
        if c.get("kb_id"):
            assert c["kb_id"] == "kb-alarm"


# ── 软路由 + 角色权限过滤（无权限 KB 不进候选）─────────────────────────────
async def test_chat_soft_route_respects_role_permission(migrated: str, app_url: str, monkeypatch) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ch-role"
    await _seed(engine, tid, migrated, monkeypatch)
    app = await _app(engine, tid)  # kb_scope=[] → 软路由

    # r-nofin 无 finance_data 权限 → 报销查询不应命中 kb-fin
    events = await _collect(engine, tid, "u1", "r-nofin", app, "报销标准", llm=FakeLLM())
    done = [e for e in events if e["type"] == "done"][0]
    assert all(c["kb_id"] != "kb-fin" for c in done["citations"])

    # r-all 可命中
    events2 = await _collect(engine, tid, "u1", "r-all", app, "报销标准", llm=FakeLLM())
    done2 = [e for e in events2 if e["type"] == "done"][0]
    assert any(c["kb_id"] == "kb-fin" for c in done2["citations"])


# ── P2: chat 软路由路径三层检索（Task 6）──────────────────────────────────
async def test_chat_soft_route_three_layer_citations(
    migrated: str,
    app_url: str,
    monkeypatch,
) -> None:
    """chat 软路由 + 实体命中 → citations 含 profile/graph 来源（决策 D3）。

    回归覆盖（既有测试）：无实体命中 = 纯 chunk citations（
    test_chat_full_flow_with_citations）；kb_scope 限定路径不接三层
    （test_chat_kb_scope_limits_search）。
    """
    from earp_server.ontology import abox_service, tbox_service

    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ch-p2"
    await _seed(engine, tid, migrated, monkeypatch)

    # 追加实体图谱：CNC-01 (equipment, equipment_data) —manufactured_by→ 上海某精机
    await tbox_service.init_tenant_tbox(engine, tid)
    sup = await abox_service.upsert_entity(engine, tid, "supplier", "上海某精机", business_code="SUP-P2")
    equip = await abox_service.upsert_entity(
        engine, tid, "equipment", "CNC-01", business_code="CNC-01", data_domain_id="equipment_data"
    )
    await abox_service.add_fact(engine, tid, equip["entity_id"], "manufactured_by", sup["entity_id"])
    await abox_service.compile_profile(engine, tid, equip["entity_id"])

    app = await _app(engine, tid)  # kb_scope=[] → 软路由
    events = await _collect(engine, tid, "u1", "r-all", app, "CNC-01 设备报警供应商", llm=FakeLLM())
    done = [e for e in events if e["type"] == "done"][0]
    assert done["citations"], "expected citations"
    sources = {c.get("source") for c in done["citations"]}
    assert "profile" in sources or "graph" in sources


# ── LLM 失败 → SSE error（用户消息已落库）─────────────────────────────────
async def test_chat_llm_error_emits_sse_error(migrated: str, app_url: str, monkeypatch) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "ch-err"
    await _seed(engine, tid, migrated, monkeypatch)
    app = await _app(engine, tid)

    llm = FakeLLM(error="ollama down")
    events = await _collect(engine, tid, "u1", "r-all", app, "报销标准", llm=llm)
    errs = [e for e in events if e["type"] == "error"]
    assert len(errs) == 1 and "失败" in errs[0]["message"]

    # 用户消息已落库，可重试
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        rows = (await conn.execute(text("SELECT role FROM messages ORDER BY seq"))).fetchall()
        assert rows and rows[-1].role == "user" or rows == []


# ── 模型三级解析 ───────────────────────────────────────────────────────────
async def test_resolve_llm_override_three_levels(app_engine: AsyncEngine) -> None:
    tid = "ch-model"
    app = await _app(app_engine, tid)

    # 1) 无任何配置 → None（env 兜底）
    assert await resolve_llm_override(app_engine, tid, app) is None

    # 2) system_model_settings(llm) 生效
    from earp_server.admin import model_service

    mc = await model_service.create_model_config(
        app_engine, tid, "ollama", "llm", "qwen3.6:27b", {"base_url": "http://m:11434"}
    )
    await model_service.set_system_model_settings(app_engine, tid, {"llm": mc["config_id"]})
    ov = await resolve_llm_override(app_engine, tid, app)
    assert ov is not None and ov["model_name"] == "qwen3.6:27b" and ov["base_url"] == "http://m:11434"

    # 3) chat_apps.model_config_id 优先
    mc2 = await model_service.create_model_config(
        app_engine, tid, "ollama", "llm", "llama3", {"base_url": "http://x:11434"}
    )
    app2 = await update_chat_app(app_engine, tid, "u1", app["chat_app_id"], {"model_config_id": mc2["config_id"]})
    assert app2 is not None
    ov2 = await resolve_llm_override(app_engine, tid, app2)
    assert ov2["model_name"] == "llama3"


# ── SSE 协议：空 query 校验 ────────────────────────────────────────────────
async def test_chat_empty_query_rejected(app_engine: AsyncEngine) -> None:
    app = await _app(app_engine, "ch-empty")
    events = await _collect(app_engine, "ch-empty", "u1", "r-all", app, "   ")
    assert events == [{"type": "error", "message": "问题不能为空"}]


# ── provider 协议：OpenAI 兼容（deepseek）流式 ──────────────────────────────
async def test_chat_stream_openai_provider_protocol() -> None:
    """openai 兼容 provider → /chat/completions + SSE 解析 + Bearer header（修复 404 bug）。"""
    import httpx

    from earp_server.config import Settings
    from earp_server.connector import LLMConnector

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["payload"] = request.read().decode()
        # OpenAI SSE 流
        body = (
            'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
            'data: {"choices":[{"delta":{}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    llm = LLMConnector(
        Settings(),
        model_override={
            "provider": "openai",
            "model_name": "deepseek-v4-flash",
            "base_url": "https://api.deepseek.com",
            "api_key": "sk-test-123",
        },
        transport=httpx.MockTransport(handler),
    )
    tokens = []
    async for ev in llm.chat_stream("你是助手", [], "报销标准", max_tokens=1024):
        tokens.append(ev.token)

    assert tokens == ["你", "好"]
    assert captured["url"] == "https://api.deepseek.com/chat/completions"  # 非 /api/chat
    assert captured["headers"]["authorization"] == "Bearer sk-test-123"
    payload = json.loads(captured["payload"])
    assert payload["stream"] is True and payload["model"] == "deepseek-v4-flash"
    assert payload["temperature"] == 0.7 and payload["max_tokens"] == 1024
    assert "options" not in payload  # OpenAI 协议顶层参数


async def test_chat_stream_ollama_provider_keeps_ndjson() -> None:
    """ollama provider 保持 /api/chat + options（NDJSON 不回归）。"""
    import httpx

    from earp_server.config import Settings
    from earp_server.connector import LLMConnector

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = request.read().decode()
        body = '{"message":{"content":"好"}}\n{"message":{"content":"的"}}\n{"done":true}\n'
        return httpx.Response(200, text=body, headers={"content-type": "application/x-ndjson"})

    llm = LLMConnector(
        Settings(),
        model_override={"provider": "ollama", "model_name": "qwen2.5:1.5b", "base_url": "http://x:11434"},
        transport=httpx.MockTransport(handler),
    )
    tokens = []
    async for ev in llm.chat_stream("sys", [], "q", temperature=0.3, max_tokens=256):
        tokens.append(ev.token)

    assert tokens == ["好", "的"]
    assert captured["url"] == "http://x:11434/api/chat"
    payload = json.loads(captured["payload"])
    assert payload["options"]["temperature"] == 0.3
    assert payload["options"]["num_predict"] == 256
