"""M3 D1 — Enrichment 模块：④③①② 全流程 + 幂等 + 手动端点。

- ③ 失效事实 revoked（完整流程：timeline + profile stale）
- ① timeline 从 messages.citations 回填（去重 source_ref=message_id）
- ② 热度 top-N 报告（不落库）
- 重复 run 幂等

测试隔离：entities.entity_id / sessions.session_id 均为单列主键（debt #7），
实体/会话 id 按租户派生（唯一），避免跨租户污染 entity_profiles JOIN。
"""

from __future__ import annotations

import asyncio
import json

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.main import create_app
from earp_server.ontology import enrichment

SECRET = "earp-dev-secret-change-in-production"


async def _seed(engine: AsyncEngine, migration_url: str, tid: str) -> None:
    e1, e2 = f"en-{tid}", f"en-{tid}b"
    cid = f"c-{tid}"
    mid = f"msg-{tid}"
    fid = f"fact-{tid}"
    uid = f"u-{tid}"
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        # 按租户派生 id 清理（单列主键跨租户共享，全局前缀清会误删他租户——按具体 id）
        for eid in (e1, e2):
            await conn.execute(
                text("DELETE FROM entity_timeline WHERE entity_id = :e"), {"e": eid}
            )
            await conn.execute(
                text("DELETE FROM entity_profiles WHERE entity_id = :e"), {"e": eid}
            )
        await conn.execute(text("DELETE FROM messages WHERE message_id = :m"), {"m": mid})
        await conn.execute(text("DELETE FROM conversations WHERE conversation_id = :c"), {"c": cid})
        await conn.execute(text("DELETE FROM users WHERE user_id = :u"), {"u": uid})
        await conn.execute(text("DELETE FROM facts WHERE fact_id = :f"), {"f": fid})
        await conn.execute(
            text("DELETE FROM entities WHERE entity_id IN (:a, :b)"), {"a": e1, "b": e2}
        )
        await conn.execute(text("DELETE FROM roles WHERE role_id = 'r-admin'"))
    await eng.dispose()
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        await conn.execute(
            text(
                "INSERT INTO data_domains (data_domain_id, tenant_id, name, description, "
                "data_classification, status) VALUES "
                "('dd-a', :t, '域A', 'x', 'internal', 'active') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, "
                "data_domain_access, is_admin) VALUES "
                "('r-admin', :t, 'Admin', '{}', 'all', '[]', TRUE) ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        await conn.execute(
            text(
                "INSERT INTO entity_types (entity_type_id, tenant_id, name, kind, "
                "data_domain_id, attributes) VALUES "
                "('equipment', :t, '设备', 'object', 'dd-a', '{}') ON CONFLICT DO NOTHING"
            ),
            {"t": tid},
        )
        # 两个实体 + 一条过期事实（valid_to 过去）
        await conn.execute(
            text(
                "INSERT INTO entities (entity_id, tenant_id, entity_type_id, name, "
                "business_code, source_mode, data_domain_id) VALUES "
                "(:e1, :t, 'equipment', '设备一', 'E-1', 'extracted', 'dd-a'), "
                "(:e2, :t, 'equipment', '设备二', 'E-2', 'extracted', 'dd-a') "
                "ON CONFLICT DO NOTHING"
            ),
            {"t": tid, "e1": e1, "e2": e2},
        )
        await conn.execute(
            text(
                "INSERT INTO facts (fact_id, tenant_id, source_entity_id, relation_type_id, "
                "target_entity_id, confidence, valid_from, valid_to, status) VALUES "
                "(:fid, :t, :e1, 'manufactured_by', :e2, 1.0, "
                "'2026-01-01T00:00:00Z', '2026-07-01T00:00:00Z', 'active')"
            ),
            {"t": tid, "e1": e1, "e2": e2, "fid": fid},
        )
        # 近窗 message：citations 落库（chat 真实引用源，review A 修复后素材）——conversation 先建（FK）
        citations = [
            {"source": "profile", "entity_id": e1, "entity_type": "equipment"},
            {"source": "graph", "entity_id": e2, "entity_type": "equipment"},
        ]
        await conn.execute(
            text(
                "INSERT INTO users (user_id, tenant_id, name, email) "
                "VALUES (:u, :t, '测试用户', :email) ON CONFLICT DO NOTHING"
            ),
            {"u": uid, "t": tid, "email": f"{uid}@t.io"},
        )
        await conn.execute(
            text(
                "INSERT INTO conversations (conversation_id, tenant_id, user_id, created_at) "
                "VALUES (:c, :t, :u, now() - interval '2 day') ON CONFLICT DO NOTHING"
            ),
            {"c": cid, "t": tid, "u": uid},
        )
        await conn.execute(
            text(
                "INSERT INTO messages (message_id, tenant_id, conversation_id, seq, role, "
                "content, citations, created_at) VALUES "
                "(:m, :t, :c, 1, 'assistant', '回答', :cit, now() - interval '1 day')"
            ),
            {"m": mid, "t": tid, "c": cid, "cit": json.dumps(citations)},
        )
        await conn.commit()


async def test_enrichment_full_flow(migrated: str, app_url: str, migration_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "en-t1"
        e1, e2 = f"en-{tid}", f"en-{tid}b"
        await _seed(engine, migration_url, tid)
        stats = await enrichment.enrichment_run(engine, tid)

        # ③ 过期事实 revoked
        assert stats["facts_revoked"] == 1
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
            r = await conn.execute(
                text(
                    "SELECT status FROM facts WHERE fact_id = :f AND tenant_id = :t"
                ),
                {"f": f"fact-{tid}", "t": tid},
            )
            assert r.mappings().first()["status"] == "revoked"

        # ① timeline 回填（2 个实体）
        assert stats["timeline_added"] == 2
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
            rows = (
                await conn.execute(
                    text(
                        "SELECT entity_id, event_type, source_ref FROM entity_timeline "
                        "WHERE tenant_id = :t"
                    ),
                    {"t": tid},
                )
            ).mappings().all()
            ev = {(r["entity_id"], r["event_type"]) for r in rows if r["source_ref"] == f"msg-{tid}"}
            assert (e1, "query.entity") in ev  # G2 映射：profile → query.entity
            assert (e2, "graph.entity") in ev  # graph → graph.entity
            # 回填行全部带 message_id 锚点（去重）
            assert sum(1 for r in rows if r["source_ref"] == f"msg-{tid}") == 2

        # ② 热度报告
        assert sum(h["refs"] for h in stats["hot_missing"]) == 2
    finally:
        await engine.dispose()


async def test_enrichment_idempotent_second_run(migrated: str, app_url: str, migration_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "en-t2"
        await _seed(engine, migration_url, tid)
        s1 = await enrichment.enrichment_run(engine, tid)
        s2 = await enrichment.enrichment_run(engine, tid)
        # 幂等：第二次不再 revoke（已 revoked）/ 不再回填（去重）
        assert s1["timeline_added"] == 2
        assert s2["facts_revoked"] == 0
        assert s2["timeline_added"] == 0
    finally:
        await engine.dispose()


async def test_enrichment_profile_recompile(migrated: str, app_url: str, migration_url: str) -> None:
    """④：无 profile 实体被重编（find_stale_profiles 覆盖）。"""
    engine = create_async_engine(app_url, pool_pre_ping=True)
    try:
        tid = "en-t3"
        await _seed(engine, migration_url, tid)
        stats = await enrichment.enrichment_run(engine, tid)
        assert stats["profiles_recompiled"] >= 2  # 两个无 profile 实体
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
            r = await conn.execute(
                text(
                    "SELECT count(*) AS c FROM entity_profiles p "
                    "JOIN entities e ON e.entity_id = p.entity_id AND e.tenant_id = :t"
                ),
                {"t": tid},
            )
            assert r.mappings().first()["c"] >= 2
    finally:
        await engine.dispose()


def _make_app(app_url: str):
    return create_app(Settings(database_url=app_url, app_env="test"))


def _token(tid: str, role_id: str = "r-admin") -> str:
    return jwt.encode(
        {"sub": "u1", "tenant_id": tid, "role_id": role_id, "exp": 9999999999},
        SECRET,
        algorithm="HS256",
    )


def test_enrichment_api_endpoint(migrated: str, app_url: str, migration_url: str) -> None:
    """手动触发端点：admin 可调；非 admin 403。"""
    tid = "en-api"
    engine = create_async_engine(app_url, pool_pre_ping=True)
    asyncio.run(_seed(engine, migrated, tid))
    app = _make_app(app_url)
    with TestClient(app) as c:
        h_ops = {"Authorization": f"Bearer {_token(tid, 'r-ops')}"}
        # r-ops 不存在（seed 只建 r-admin）——任意角色 401/403 语义
        assert c.post("/v1/ontology/enrichment/run", headers=h_ops).status_code in (401, 403)
        h = {"Authorization": f"Bearer {_token(tid, 'r-admin')}"}
        r = c.post("/v1/ontology/enrichment/run", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) >= {"profiles_recompiled", "facts_revoked", "timeline_added", "hot_missing"}
    asyncio.run(engine.dispose())
