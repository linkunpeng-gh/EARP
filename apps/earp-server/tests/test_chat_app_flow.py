"""Chatflow F1 — flow_schema 落库 + orchestration 模式（migration 0024 + 校验 + 端点）。

覆盖：create/update/publish 的 orchestration + flow_schema 校验语义、JSONB 往返、
发布门禁（flow 变更纳入发布评审）、扩展节点类型白名单、路由级 422。
镜像 test_chat_apps 的 app_engine fixture 模式（服务级直调）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.config import Settings
from earp_server.conversation import chat_app_service as svc
from earp_server.main import create_app


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


# ── flow_schema 构造 helper ──────────────────────────────────────────────────


def _flow(nodes: list[dict], edges: list[dict]) -> dict:
    return {"nodes": nodes, "edges": edges}


def _step_node(nid: str, msg: str = "hello") -> dict:
    return {
        "id": nid,
        "type": "step",
        "data": {"capability_call": {"adapter_type": "demo.echo", "input": {"msg": msg}}},
    }


def _sequential_flow() -> dict:
    return _flow(
        [
            {"id": "start", "type": "start", "data": {}},
            _step_node("n1"),
            _step_node("n2"),
            {"id": "end", "type": "end", "data": {}},
        ],
        [
            {"source": "start", "target": "n1"},
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "end"},
        ],
    )


def _cycle_flow() -> dict:
    return _flow(
        [
            {"id": "start", "type": "start", "data": {}},
            _step_node("n1"),
            _step_node("n2"),
            {"id": "end", "type": "end", "data": {}},
        ],
        [
            {"source": "start", "target": "n1"},
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n1"},  # 环
            {"source": "n2", "target": "end"},
        ],
    )


def _extended_flow() -> dict:
    """设计稿 §5 示例 A 的声明版：QU/Condition/Capability/Human Approval 节点。"""
    return _flow(
        [
            {"id": "start", "type": "start", "data": {}},
            {"id": "q1", "type": "qu", "data": {"prompt": "解析 CNC-01"}},
            {
                "id": "c1",
                "type": "condition",
                "data": {"condition": {"left": "q1.output.status", "op": "==", "right": "faulty"}},
            },
            {"id": "n2", "type": "capability", "data": {"capability_call": {"adapter_type": "demo.echo"}}},
            {"id": "h1", "type": "human_approval", "data": {}},
            {"id": "end", "type": "end", "data": {}},
        ],
        [
            {"source": "start", "target": "q1"},
            {"source": "q1", "target": "c1"},
            {"source": "c1", "target": "n2", "sourceHandle": "true"},
            {"source": "c1", "target": "h1", "sourceHandle": "false"},
            {"source": "n2", "target": "end"},
            {"source": "h1", "target": "end"},
        ],
    )


# ── create ───────────────────────────────────────────────────────────────────


class TestCreate:
    async def test_create_defaults_auto_with_null_schema(self, app_engine: AsyncEngine) -> None:
        app = await svc.create_chat_app(app_engine, "f1-t1", "u1", "默认问答")
        assert app["orchestration"] == "auto"
        assert app["flow_schema"] is None

    async def test_create_flow_with_valid_schema(self, app_engine: AsyncEngine) -> None:
        app = await svc.create_chat_app(
            app_engine, "f1-t1", "u1", "流程应用", orchestration="flow", flow_schema=_sequential_flow()
        )
        assert app["orchestration"] == "flow"
        assert app["flow_schema"] == _sequential_flow()  # JSONB 往返
        assert app["status"] == "draft"

    async def test_create_flow_with_extended_node_types(self, app_engine: AsyncEngine) -> None:
        """设计稿 §3 全节点类型白名单可存（F1 声明层，F2 执行逐步跟上）。"""
        app = await svc.create_chat_app(
            app_engine, "f1-t1", "u1", "扩展图", orchestration="flow", flow_schema=_extended_flow()
        )
        assert app["orchestration"] == "flow"
        assert app["flow_schema"]["nodes"][1]["type"] == "qu"

    async def test_create_flow_missing_schema_rejected(self, app_engine: AsyncEngine) -> None:
        with pytest.raises(ValueError, match="flow_schema is required"):
            await svc.create_chat_app(app_engine, "f1-t1", "u1", "缺图", orchestration="flow")

    async def test_create_flow_cycle_rejected(self, app_engine: AsyncEngine) -> None:
        with pytest.raises(ValueError, match="invalid flow_schema"):
            await svc.create_chat_app(
                app_engine, "f1-t1", "u1", "坏图", orchestration="flow", flow_schema=_cycle_flow()
            )

    async def test_create_bad_orchestration_rejected(self, app_engine: AsyncEngine) -> None:
        with pytest.raises(ValueError, match="orchestration must be one of"):
            await svc.create_chat_app(app_engine, "f1-t1", "u1", "非法模式", orchestration="dag")

    async def test_create_auto_with_invalid_schema_rejected(self, app_engine: AsyncEngine) -> None:
        """auto 模式传坏图也拒（坏图存不进去；切回 flow 不重画）。"""
        with pytest.raises(ValueError, match="invalid flow_schema"):
            await svc.create_chat_app(app_engine, "f1-t1", "u1", "auto 坏图", flow_schema=_cycle_flow())


# ── update ───────────────────────────────────────────────────────────────────


class TestUpdate:
    async def _base_app(self, app_engine: AsyncEngine) -> dict:
        return await svc.create_chat_app(app_engine, "f1-t1", "u1", "待切模式")

    async def test_switch_to_flow_with_schema(self, app_engine: AsyncEngine) -> None:
        app = await self._base_app(app_engine)
        updated = await svc.update_chat_app(
            app_engine,
            "f1-t1",
            "u1",
            app["chat_app_id"],
            {"orchestration": "flow", "flow_schema": _sequential_flow()},
        )
        assert updated is not None
        assert updated["orchestration"] == "flow"
        assert updated["flow_schema"] == _sequential_flow()

    async def test_switch_to_flow_uses_existing_schema(self, app_engine: AsyncEngine) -> None:
        """auto 模式已存 schema → 切 flow 不再传 schema 也通过。"""
        app = await self._base_app(app_engine)
        await svc.update_chat_app(app_engine, "f1-t1", "u1", app["chat_app_id"], {"flow_schema": _sequential_flow()})
        updated = await svc.update_chat_app(app_engine, "f1-t1", "u1", app["chat_app_id"], {"orchestration": "flow"})
        assert updated is not None and updated["orchestration"] == "flow"

    async def test_update_flow_invalid_schema_rejected(self, app_engine: AsyncEngine) -> None:
        app = await self._base_app(app_engine)
        with pytest.raises(ValueError, match="invalid flow_schema"):
            await svc.update_chat_app(app_engine, "f1-t1", "u1", app["chat_app_id"], {"flow_schema": _cycle_flow()})
        # 不落库：读回仍 auto + null
        fresh = await svc.get_chat_app(app_engine, "f1-t1", app["chat_app_id"])
        assert fresh is not None and fresh["orchestration"] == "auto" and fresh["flow_schema"] is None

    async def test_switch_back_to_auto_keeps_schema(self, app_engine: AsyncEngine) -> None:
        """auto→flow→auto：flow_schema 保留（切回不重画）。"""
        app = await self._base_app(app_engine)
        await svc.update_chat_app(
            app_engine, "f1-t1", "u1", app["chat_app_id"], {"orchestration": "flow", "flow_schema": _sequential_flow()}
        )
        back = await svc.update_chat_app(app_engine, "f1-t1", "u1", app["chat_app_id"], {"orchestration": "auto"})
        assert back is not None and back["orchestration"] == "auto"
        assert back["flow_schema"] == _sequential_flow()

    async def test_update_flow_reverts_published_to_draft(self, app_engine: AsyncEngine) -> None:
        """既有语义：published 编辑 → 回 draft（需重新发布），flow 字段同。"""
        app = await svc.create_chat_app(
            app_engine, "f1-t1", "u1", "已发布", orchestration="flow", flow_schema=_sequential_flow()
        )
        pub = await svc.publish_chat_app(app_engine, "f1-t1", "u1", app["chat_app_id"])
        assert pub is not None and pub["status"] == "published"
        updated = await svc.update_chat_app(app_engine, "f1-t1", "u1", app["chat_app_id"], {"description": "改"})
        assert updated is not None and updated["status"] == "draft"


# ── publish 门禁（设计稿 §9 开放问题 1：flow 变更纳入发布评审）────────────────


class TestPublish:
    async def test_publish_flow_with_valid_schema(self, app_engine: AsyncEngine) -> None:
        app = await svc.create_chat_app(
            app_engine, "f1-t1", "u1", "发布流程", orchestration="flow", flow_schema=_sequential_flow()
        )
        pub = await svc.publish_chat_app(app_engine, "f1-t1", "u1", app["chat_app_id"])
        assert pub is not None and pub["status"] == "published"

    async def test_publish_flow_rejects_invalid_schema(self, app_engine: AsyncEngine) -> None:
        """手工改库/历史坏图 → 发布被拒（发布评审）。"""
        app = await svc.create_chat_app(
            app_engine, "f1-t1", "u1", "坏图发布", orchestration="flow", flow_schema=_sequential_flow()
        )
        # 绕过 update 校验直接改坏图（模拟历史数据/直接改库）
        from sqlalchemy import text

        async with app_engine.begin() as conn:
            await conn.execute(text("SET LOCAL earp.tenant_id = 'f1-t1'"))
            await conn.execute(
                text("UPDATE chat_apps SET flow_schema = :bad WHERE chat_app_id = :id"),
                {"bad": __import__("json").dumps(_cycle_flow()), "id": app["chat_app_id"]},
            )
        with pytest.raises(ValueError, match="invalid flow_schema"):
            await svc.publish_chat_app(app_engine, "f1-t1", "u1", app["chat_app_id"])

    async def test_publish_auto_ignores_schema_gate(self, app_engine: AsyncEngine) -> None:
        """auto 模式发布不受 flow 门禁影响（存量语义）。"""
        app = await svc.create_chat_app(app_engine, "f1-t1", "u1", "auto 发布")
        pub = await svc.publish_chat_app(app_engine, "f1-t1", "u1", app["chat_app_id"])
        assert pub is not None and pub["status"] == "published"


# ── 路由级（JWT + 422 错误信息透传）───────────────────────────────────────

_DEV_SECRET = "earp-dev-secret-change-in-production"


def _auth_token(tenant_id: str = "f1-t1") -> dict[str, str]:
    import jwt as _jwt

    token = _jwt.encode(
        {"sub": "u1", "tenant_id": tenant_id, "role_id": "r1", "exp": 9999999999},
        _DEV_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


class TestRoutes:
    async def test_create_flow_invalid_returns_422(self, migrated: str, app_url: str) -> None:
        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app) as client:
            resp = client.post(
                "/chat_apps",
                json={"name": "坏图", "orchestration": "flow", "flow_schema": _cycle_flow()},
                headers=_auth_token(),
            )
            assert resp.status_code == 422
            detail = resp.json()["detail"]
            assert "invalid flow_schema" in detail
            assert "cycle" in detail

    async def test_create_flow_valid_returns_201(self, migrated: str, app_url: str) -> None:
        app = create_app(Settings(database_url=app_url, app_env="test"))
        with TestClient(app) as client:
            resp = client.post(
                "/chat_apps",
                json={"name": "流程应用", "orchestration": "flow", "flow_schema": _sequential_flow()},
                headers=_auth_token(),
            )
            assert resp.status_code == 201
            body = resp.json()
            assert body["orchestration"] == "flow"
            assert body["flow_schema"] == _sequential_flow()
