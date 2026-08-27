"""tech-debt #9 漏洞回归 — search_chunks 角色 data_domain_access 域门禁。

背景（2026-08-18 FDE 反馈）：普通角色只授权一个部门（数据域），但召回测试
可召回其他部门数据。根因：search_chunks 只按 kb.accessible_roles（大多为空）
过滤，不按角色 data_domain_access 过滤——无 scope 全租户兜底、显式 DD/KB scope
三条路径均泄露。修复：非 admin 角色一律与允许域交叠（admin 不过滤）。
"""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from earp_server.knowledge.chunk_service import create_chunks
from earp_server.knowledge.document_service import create_document
from earp_server.knowledge.embedding_service import embed_chunks, embed_query
from earp_server.knowledge.search_service import search_chunks

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
    import earp_server.knowledge.embedding_service as svc
    import earp_server.knowledge.routing as routing

    provider = _BigramStubProvider()
    monkeypatch.setattr(svc, "get_embedding_provider", lambda: provider)
    monkeypatch.setattr(routing, "get_embedding_provider", lambda: provider)


async def _purge(migration_url: str) -> None:
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        await conn.execute(text("DELETE FROM chunks WHERE knowledge_base_id IN ('kb-fin','kb-equip')"))
        await conn.execute(text("DELETE FROM documents WHERE knowledge_base_id IN ('kb-fin','kb-equip')"))
        await conn.execute(text("DELETE FROM knowledge_bases WHERE knowledge_base_id IN ('kb-fin','kb-equip')"))
        await conn.execute(text("DELETE FROM data_domains WHERE data_domain_id IN ('dd-fin','dd-equip')"))
        await conn.execute(text("DELETE FROM roles WHERE role_id IN ('r-sg-admin','r-sg-one','r-sg-none')"))
    await eng.dispose()


async def _seed(engine, migration_url: str, tid: str, monkeypatch) -> None:
    _install_stub(monkeypatch)
    await _purge(migration_url)
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, "
                "data_classification, status) VALUES "
                "('dd-fin', :t, '财务', '报销', 'internal', 'active'), "
                "('dd-equip', :t, '设备', '报警', 'internal', 'active') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.execute(
            text(
                "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name, data_domain_id, "
                "description, metadata_schema) VALUES "
                "('kb-fin', :t, '财务手册', 'dd-fin', '报销制度', '[]'), "
                "('kb-equip', :t, '设备手册', 'dd-equip', '报警阈值', '[]') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, "
                "data_domain_access, is_admin) VALUES "
                "('r-sg-admin', :t, 'Admin', '{}', 'all', '[]', TRUE), "
                "('r-sg-one', :t, '单域', '{}', 'all', '[{\"data_domain_id\": \"dd-equip\"}]', FALSE), "
                "('r-sg-none', :t, '无域', '{}', 'all', '[]', FALSE) ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.commit()
    for kid, title, content in [
        ("kb-fin", "2024报销标准", "2024年报销标准：住宿每天500元。"),
        ("kb-equip", "报警阈值说明", "设备报警阈值：主轴温度超过85度触发报警。"),
    ]:
        doc = await create_document(engine, tid, kid, content, title=title)
        cids = await create_chunks(engine, tid, doc["document_id"], content)
        await embed_chunks(engine, tid, cids)


async def test_unscoped_search_gated_by_role_domains(migrated: str, app_url: str, monkeypatch) -> None:
    """无 scope 全租户搜索：单域角色只见本域 chunk（admin 全量）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "sg-t1"
    await _seed(engine, migrated, tid, monkeypatch)
    q_emb = await embed_query("报销制度")

    hits_one = await search_chunks(
        engine,
        tid,
        q_emb,
        "r-sg-one",
        top_k=10,
        embedding_dim=DIM,
        query_text="报销制度",
        mode="hybrid",
        rerank=False,
    )
    assert hits_one, "单域角色应至少召回本域结果"
    assert all(h["kb_id"] == "kb-equip" for h in hits_one), [h["kb_id"] for h in hits_one]

    hits_admin = await search_chunks(
        engine,
        tid,
        q_emb,
        "r-sg-admin",
        top_k=10,
        embedding_dim=DIM,
        query_text="报销制度",
        mode="hybrid",
        rerank=False,
    )
    assert any(h["kb_id"] == "kb-fin" for h in hits_admin), "admin 全权限应可见财务 KB"


async def test_explicit_dd_scope_cannot_bypass_role_gate(migrated: str, app_url: str, monkeypatch) -> None:
    """显式 data_domain_ids 传其他域 → 与角色允许域交叠为空 → 无结果（防绕过）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "sg-t2"
    await _seed(engine, migrated, tid, monkeypatch)
    q_emb = await embed_query("报销制度")

    hits = await search_chunks(
        engine,
        tid,
        q_emb,
        "r-sg-one",
        top_k=10,
        embedding_dim=DIM,
        data_domain_ids=["dd-fin"],
        query_text="报销制度",
        mode="hybrid",
        rerank=False,
    )
    assert all(h["kb_id"] != "kb-fin" for h in hits), "单域角色不得通过显式 scope 召回其他域"


async def test_explicit_kb_scope_cannot_bypass_role_gate(migrated: str, app_url: str, monkeypatch) -> None:
    """显式 knowledge_base_ids 传其他域 KB → 无结果（chat kb_scope 同源防绕过）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "sg-t3"
    await _seed(engine, migrated, tid, monkeypatch)
    q_emb = await embed_query("报销制度")

    hits = await search_chunks(
        engine,
        tid,
        q_emb,
        "r-sg-one",
        top_k=10,
        embedding_dim=DIM,
        knowledge_base_ids=["kb-fin"],
        query_text="报销制度",
        mode="hybrid",
        rerank=False,
    )
    assert hits == [], "单域角色不得通过显式 KB scope 召回其他域 KB"


async def test_no_domain_access_fail_closed(migrated: str, app_url: str, monkeypatch) -> None:
    """无任何域授权 → 无结果（fail-closed）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "sg-t4"
    await _seed(engine, migrated, tid, monkeypatch)
    q_emb = await embed_query("报销制度")

    hits = await search_chunks(
        engine,
        tid,
        q_emb,
        "r-sg-none",
        top_k=10,
        embedding_dim=DIM,
        query_text="报销制度",
        mode="hybrid",
        rerank=False,
    )
    assert hits == [], "无域角色必须 fail-closed"


async def test_fallback_kbs_gated_by_role_domains(migrated: str, app_url: str, monkeypatch) -> None:
    """D4 全租户 KB 兜底必须限定角色允许域（泄露根因 2026-08-18）。

    单域角色查「报销」→ 关键词命中 dd-fin 但被权限滤掉 → candidate_dds 空 →
    兜底触发：此前返回任意域 KB（泄露 + 本域 KB 被挤掉误伤 0 结果）；
    修复后只返回本域（dd-equip）KB。admin 兜底不过滤。
    """
    from earp_server.knowledge.routing import build_routing_index, route_query

    engine = create_async_engine(app_url, pool_pre_ping=True)
    tid = "sg-t5"
    await _seed(engine, migrated, tid, monkeypatch)
    # 再加两个「报销」相关的域/KB（描述与查询更近）→ top-3 向量候选挤掉 dd-equip
    # → r-sg-one 的候选全被权限滤掉 → D4 兜底触发（此前返回任意域 KB 泄露）
    from sqlalchemy import text

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, "
                "data_classification, status) VALUES "
                "('dd-extra1', :t, '差旅', '报销差旅', 'internal', 'active'), "
                "('dd-extra2', :t, '发票', '报销发票财务', 'internal', 'active') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.execute(
            text(
                "INSERT INTO knowledge_bases (knowledge_base_id, tenant_id, name, data_domain_id, "
                "description, metadata_schema) VALUES "
                "('kb-extra1', :t, '差旅手册', 'dd-extra1', '报销差旅制度', '[]'), "
                "('kb-extra2', :t, '发票手册', 'dd-extra2', '报销发票财务', '[]') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.commit()
    await build_routing_index(engine, tid)

    q_emb = await embed_query("报销")
    routed = await route_query(engine, tid, "报销", q_emb, "r-sg-one", top_n=3, top_k=3)
    assert routed["fallback_used"] is True, routed
    assert routed["candidate_dds"] == []
    assert routed["candidate_kbs"], "兜底应至少返回本域 KB"
    assert all(k["data_domain_id"] == "dd-equip" for k in routed["candidate_kbs"]), [
        k["data_domain_id"] for k in routed["candidate_kbs"]
    ]

    # admin 对照：同查询不过滤（候选含 r-sg-one 无权访问的 dd-extra1/dd-extra2）
    routed_admin = await route_query(engine, tid, "报销", q_emb, "r-sg-admin", top_n=3, top_k=3)
    assert routed_admin["fallback_used"] is False, routed_admin
    admin_dds = {c["data_domain_id"] for c in routed_admin["candidate_dds"]}
    assert admin_dds & {"dd-extra1", "dd-extra2", "dd-fin"}, "admin 全权限应可见其他域候选"
