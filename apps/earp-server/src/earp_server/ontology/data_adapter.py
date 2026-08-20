"""M3 A2 — 轻量取数 adapter：REST（httpx 直连）/ DB（SQLAlchemy 外部 engine）。

服务端内置实现（D5：不引 connector SDK——DatabaseConnector 是 stub 无复用价值）；
同步（B3）与 virtual live（C1）共用 `fetch()` 统一入口，按 connector 配置的
adapter_type 分派。

外部连接不经过 EARP RLS（数据在外部系统），virtual 结果权限靠实体
data_domain_id 继承声明（G7）；取数失败抛 ConnectorFetchError，调用方兜底
（不假造值）。

REST cfg（A3 契约）：{base_url, path, method?, auth_type?(none|basic|bearer),
  username?, password?, token?, headers?, timeout_seconds?}
DB   cfg（A3 契约）：{conn_url, table, columns[], where?{col: param_key},
  since_field?, limit?}——列/表名白名单校验防注入，值全部绑定参数。
"""

from __future__ import annotations

import logging
import re

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0
_MAX_ROWS = 10000
_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class ConnectorFetchError(Exception):
    """取数失败（配置缺失/超时/连接/HTTP/表名非法）——调用方兜底，不假造值。"""


def _check_ident(value: str, what: str) -> str:
    if not value or not _IDENT_RE.match(value):
        raise ConnectorFetchError(f"非法{what}名（白名单仅允许字母/数字/下划线）: {value!r}")
    return value


async def fetch_rest(cfg: dict, params: dict | None = None) -> list[dict]:
    """REST 取数：GET/POST base_url + path，Basic/Bearer/Header auth + query 透传。

    响应兼容裸数组与 {data: [...]} 包装（A3 契约）。非 2xx / 超时 / 连接失败 → 抛错。
    """
    base_url = (cfg.get("base_url") or "").rstrip("/")
    path = cfg.get("path") or ""
    method = (cfg.get("method") or "GET").upper()
    timeout = float(cfg.get("timeout_seconds") or _DEFAULT_TIMEOUT)
    if not base_url:
        raise ConnectorFetchError("REST 配置缺少 base_url")

    headers = dict(cfg.get("headers") or {})
    auth_type = cfg.get("auth_type") or "none"
    if auth_type == "basic":
        username = cfg.get("username") or ""
        password = cfg.get("password") or ""
        import base64

        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        headers.setdefault("Authorization", f"Basic {token}")
    elif auth_type == "bearer":
        headers.setdefault("Authorization", f"Bearer {cfg.get('token') or ''}")

    query = {k: str(v) for k, v in (params or {}).items() if v is not None}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                resp = await client.get(f"{base_url}{path}", params=query, headers=headers)
            elif method == "POST":
                resp = await client.post(f"{base_url}{path}", json=query, headers=headers)
            else:
                raise ConnectorFetchError(f"不支持的 method: {method}（一期仅 GET/POST）")
    except httpx.TimeoutException as e:
        raise ConnectorFetchError(f"REST 取数超时（{timeout}s）: {base_url}{path}") from e
    except httpx.HTTPError as e:
        raise ConnectorFetchError(f"REST 取数连接失败: {base_url}{path}: {e}") from e
    if not resp.is_success:
        raise ConnectorFetchError(f"REST 取数 HTTP {resp.status_code}: {base_url}{path}")

    data = resp.json()
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return [r for r in data["data"] if isinstance(r, dict)]
    raise ConnectorFetchError(f"REST 响应格式不支持（需裸数组或 {{data:[...]}}）: {base_url}{path}")


async def fetch_db(cfg: dict, params: dict | None = None) -> list[dict]:
    """DB 取数：外部库只读 SELECT。表/列名白名单校验，值全部绑定参数。

    where: {"列名": "param_key"} → 等值绑定（params[param_key] 提供值）
    since_field: params["since"] 存在时 → WHERE {since_field} >= :since（增量同步）
    """
    conn_url = cfg.get("conn_url") or ""
    if not conn_url:
        raise ConnectorFetchError("DB 配置缺少 conn_url")
    table = _check_ident(cfg.get("table") or "", "表")
    raw_cols = cfg.get("columns") or ["*"]
    cols = ", ".join(_check_ident(c, "列") for c in raw_cols if c != "*") if raw_cols != ["*"] else "*"
    limit = min(int(cfg.get("limit") or _MAX_ROWS), _MAX_ROWS)

    clauses: list[str] = []
    bind: dict = {}
    params = params or {}
    for col, key in (cfg.get("where") or {}).items():
        _check_ident(col, "列")
        if key in params and params[key] is not None:
            clauses.append(f"{col} = :{col}")
            bind[col] = params[key]
    since_field = cfg.get("since_field")
    if since_field and params.get("since") is not None:
        _check_ident(since_field, "列")
        clauses.append(f"{since_field} >= :since")
        bind["since"] = params["since"]

    sql = f"SELECT {cols} FROM {table}"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += f" LIMIT {limit}"

    engine = create_async_engine(conn_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(text(sql), bind)
            return [dict(r._mapping) for r in rows]
    except Exception as e:
        logger.warning("fetch_db failed: %s", e, exc_info=True)
        raise ConnectorFetchError(f"DB 取数失败: {table}: {e}") from e
    finally:
        await engine.dispose()


async def fetch(cfg: dict, params: dict | None = None) -> list[dict]:
    """统一取数入口（B3 同步 / C1 virtual live 共用）。"""
    adapter_type = cfg.get("adapter_type") or "rest"
    if adapter_type == "rest":
        return await fetch_rest(cfg, params)
    if adapter_type == "db":
        return await fetch_db(cfg, params)
    raise ConnectorFetchError(f"未知 adapter_type: {adapter_type}")
