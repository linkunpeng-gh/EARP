"""M3 A2 — 轻量取数 adapter：REST（httpx mock）/ DB（临时表）取数与安全校验。

REST 用 httpx.MockTransport（不经过网络层）；DB 用迁移角色在测试库建临时表
+ GRANT SELECT earp_app（无 RLS 策略的表，应用角色可读）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from earp_server.ontology import data_adapter

# ── REST ──────────────────────────────────────────────────────────────────────
# 模块导入时捕获原始 AsyncClient（monkeypatch 会改全局 httpx 模块属性，
# fake_client 内部必须引用原始类，否则递归替换）。
_ORIG_ASYNC_CLIENT = httpx.AsyncClient

Handler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


async def _rest(fetch_fn, cfg: dict, params: dict | None = None, handler: Handler | None = None):
    def fake_client(**kw):
        assert handler is not None
        return _ORIG_ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kw)  # type: ignore[arg-type]

    import earp_server.ontology.data_adapter as mod

    orig = mod.httpx.AsyncClient
    mod.httpx.AsyncClient = fake_client  # type: ignore[assignment]
    try:
        return await fetch_fn(cfg, params)
    finally:
        mod.httpx.AsyncClient = orig


async def test_rest_bare_array() -> None:
    def handler(request):
        assert request.url.params["code"] == "E-1"  # query 透传
        return httpx.Response(200, json=[{"code": "E-1", "name": "设备一"}])

    rows = await _rest(
        data_adapter.fetch_rest,
        {"base_url": "http://mid/api", "path": "/equip"},
        {"code": "E-1"},
        handler,
    )
    assert rows == [{"code": "E-1", "name": "设备一"}]


async def test_rest_data_wrapper() -> None:
    def handler(request):
        return httpx.Response(200, json={"code": 0, "data": [{"code": "E-2"}]})

    rows = await _rest(data_adapter.fetch_rest, {"base_url": "http://mid/api", "path": "/x"}, None, handler)
    assert rows == [{"code": "E-2"}]


async def test_rest_basic_auth_header() -> None:
    def handler(request):
        assert request.headers["authorization"] == "Basic dTpw"  # base64("u:p")
        return httpx.Response(200, json=[])

    await _rest(
        data_adapter.fetch_rest,
        {"base_url": "http://mid", "path": "/", "auth_type": "basic", "username": "u", "password": "p"},
        None,
        handler,
    )


async def test_rest_bearer_auth_header() -> None:
    def handler(request):
        assert request.headers["authorization"] == "Bearer tok-1"
        return httpx.Response(200, json=[])

    await _rest(
        data_adapter.fetch_rest,
        {"base_url": "http://mid", "path": "/", "auth_type": "bearer", "token": "tok-1"},
        None,
        handler,
    )


async def test_rest_http_error_raises() -> None:
    def handler(request):
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(data_adapter.ConnectorFetchError):
        await _rest(data_adapter.fetch_rest, {"base_url": "http://mid", "path": "/"}, None, handler)


async def test_rest_bad_response_shape_raises() -> None:
    def handler(request):
        return httpx.Response(200, json={"foo": 1})  # 既非数组也非 {data: []}

    with pytest.raises(data_adapter.ConnectorFetchError):
        await _rest(data_adapter.fetch_rest, {"base_url": "http://mid", "path": "/"}, None, handler)


async def test_rest_missing_base_url_raises() -> None:
    with pytest.raises(data_adapter.ConnectorFetchError):
        await data_adapter.fetch_rest({"path": "/"}, None)


async def test_rest_timeout_raises() -> None:
    # MockTransport 不经过网络层（T2 实证：handler 内 sleep 不受 timeout 约束），
    # 用抛 TimeoutException 的假 client 覆盖超时分支。
    class BoomClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise httpx.TimeoutException("timeout")

        async def post(self, *a, **k):
            raise httpx.TimeoutException("timeout")

    import earp_server.ontology.data_adapter as mod

    orig = mod.httpx.AsyncClient
    mod.httpx.AsyncClient = BoomClient  # type: ignore[assignment]
    try:
        with pytest.raises(data_adapter.ConnectorFetchError):
            await data_adapter.fetch_rest({"base_url": "http://mid", "path": "/", "timeout_seconds": 0.05})
    finally:
        mod.httpx.AsyncClient = orig


async def test_unknown_adapter_type_raises() -> None:
    with pytest.raises(data_adapter.ConnectorFetchError):
        await data_adapter.fetch({"adapter_type": "ftp"})


# ── DB ────────────────────────────────────────────────────────────────────────
async def _setup_temp_table(migration_url: str) -> None:
    eng = create_async_engine(migration_url)
    async with eng.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS m3_adapt_test ("
                "code VARCHAR(32) PRIMARY KEY, name TEXT, updated_at TIMESTAMPTZ)"
            )
        )
        await conn.execute(text("DELETE FROM m3_adapt_test"))
        await conn.execute(
            text(
                "INSERT INTO m3_adapt_test VALUES "
                "('E-1', '设备一', '2026-08-01T00:00:00Z'), "
                "('E-2', '设备二', '2026-08-10T00:00:00Z')"
            )
        )
        await conn.execute(text("GRANT SELECT ON m3_adapt_test TO earp_app"))
    await eng.dispose()


async def test_db_fetch_reads_rows(migrated: str, migration_url: str) -> None:
    await _setup_temp_table(migration_url)
    cfg = {"adapter_type": "db", "conn_url": migration_url, "table": "m3_adapt_test", "columns": ["code", "name"]}
    rows = await data_adapter.fetch(cfg)
    assert {r["code"] for r in rows} == {"E-1", "E-2"}
    assert "updated_at" not in rows[0]  # 列白名单：只取声明的列


async def test_db_fetch_where_binding(migrated: str, migration_url: str) -> None:
    await _setup_temp_table(migration_url)
    cfg = {
        "adapter_type": "db",
        "conn_url": migration_url,
        "table": "m3_adapt_test",
        "columns": ["code"],
        "where": {"code": "business_code"},
    }
    rows = await data_adapter.fetch(cfg, {"business_code": "E-2"})
    assert rows == [{"code": "E-2"}]


async def test_db_fetch_since_incremental(migrated: str, migration_url: str) -> None:
    await _setup_temp_table(migration_url)
    cfg = {
        "adapter_type": "db",
        "conn_url": migration_url,
        "table": "m3_adapt_test",
        "columns": ["code"],
        "since_field": "updated_at",
    }
    rows = await data_adapter.fetch(cfg, {"since": "2026-08-05T00:00:00Z"})
    assert [r["code"] for r in rows] == ["E-2"]  # 只有 8-10 更新的行


async def test_db_fetch_illegal_table_name_raises(migrated: str, migration_url: str) -> None:
    cfg = {"adapter_type": "db", "conn_url": migration_url, "table": "x; DROP TABLE y", "columns": ["*"]}
    with pytest.raises(data_adapter.ConnectorFetchError):
        await data_adapter.fetch(cfg)


async def test_db_fetch_illegal_column_raises(migrated: str, migration_url: str) -> None:
    cfg = {"adapter_type": "db", "conn_url": migration_url, "table": "m3_adapt_test", "columns": ["code; DROP"]}
    with pytest.raises(data_adapter.ConnectorFetchError):
        await data_adapter.fetch(cfg)


async def test_db_fetch_missing_conn_url_raises() -> None:
    with pytest.raises(data_adapter.ConnectorFetchError):
        await data_adapter.fetch({"adapter_type": "db", "table": "t"})
