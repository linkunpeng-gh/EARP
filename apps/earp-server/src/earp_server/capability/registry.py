"""Capability registration + role-aware discovery + Redis token-bucket rate limiter.

All `domain` column references in this file refer to Business Domain
(not Data Domain—those are a separate v2.1 concept in data_domains table).
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

if TYPE_CHECKING:
    from earp_server.config import Settings

logger = logging.getLogger(__name__)

_DEMO_CAPABILITY = {
    "capability_id": "cap-demo-echo",
    "domain": "demo",
    "name": "echo",
    "type": "query",
    "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}},
    "required_permissions": ["demo.echo"],
    "version": "1.0.0",
    # 通用执行器任务书 D7：补显式执行声明（兼容回退仍保留）
    "execution": {"adapter": "demo.echo"},
}

# Standard Data Domains — aligned with the admin UI hardcoded options
# (knowledge.html / data-domains.html), planner business dictionary and
# ontology TBox seeds. Seeded per-tenant by seed_demo_tenant().
_STANDARD_DATA_DOMAINS: tuple[tuple[str, str], ...] = (
    ("equipment_data", "设备数据"),
    ("hr_data", "人事数据"),
    ("corporate_data", "企业数据"),
    ("production_data", "生产数据"),
    ("supply_chain_data", "供应链数据"),
    ("quality_data", "质量数据"),
)

# Demo role with permissions matching the Business Dictionary capabilities.
# tech-debt #9：is_admin=True 全权限通用机制——不再查租户 DD 配 data_domain_access
# （seed 特判移除，新建 DD 自动可见）；tbox.approve 供 TBox 审批人角色门禁。
_DEMO_ROLE = {
    "role_id": "r1",
    "name": "Admin",
    "permissions": ["demo.echo", "query.users", "create.alarm", "query.alarms", "tbox.approve"],
    "data_scope": "all",
    "is_admin": True,
}


async def register_demo(engine: AsyncEngine, tenant_id: str) -> None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        schema_json = json.dumps(_DEMO_CAPABILITY["input_schema"])
        execution_json = json.dumps(_DEMO_CAPABILITY["execution"])
        await conn.exec_driver_sql(
            f"INSERT INTO business_capabilities (capability_id, tenant_id, domain, name, type, "
            f"input_schema, output_schema, required_permissions, version, execution) "
            f"VALUES ('cap-demo-echo', '{tenant_id}', 'demo', 'echo', 'query', "
            f"'{schema_json}', '{{}}', '{{demo.echo}}', '1.0.0', '{execution_json}') "
            f"ON CONFLICT (capability_id, tenant_id) DO NOTHING"
        )
        await conn.commit()


async def seed_demo_tenant(engine: AsyncEngine, tenant_id: str) -> None:
    """Seed the demo tenant baseline: tenant, user, role, data domains, demo capability.

    Idempotent (ON CONFLICT DO NOTHING) — safe to call at every startup.
    Fixes dev debugging blockers:
      - invoke 403: PolicyLayer found no role permissions (roles table empty)
      - create KB 500: data_domains missing standard domain ids (FK violation)
      - create conversation 500: conversations.user_id FK -> users table empty
    """
    async with engine.connect() as conn:
        # tenants has no RLS (top-level table)
        await conn.execute(
            text(
                "INSERT INTO tenants (tenant_id, name, status) VALUES (:tid, :name, 'active') "
                "ON CONFLICT (tenant_id) DO NOTHING"
            ),
            {"tid": tenant_id, "name": "Demo Tenant"},
        )
        # users / roles / data_domains / business_capabilities are RLS-scoped
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO users (user_id, tenant_id, name, email) "
                "VALUES (:uid, :tid, 'Admin', 'admin@demo.local') "
                "ON CONFLICT (user_id) DO NOTHING"
            ),
            {"uid": "u1", "tid": tenant_id},
        )
        # Admin role gets domain-wide access: is_admin=True（tech-debt #9 通用机制）——
        # 跳过 data_domain_access 域过滤，新建 DD 自动可见（seed 特判移除）。
        await conn.execute(
            text(
                "INSERT INTO roles (role_id, tenant_id, name, permissions, data_scope, data_domain_access, is_admin) "
                "VALUES (:rid, :tid, :name, :perms, :scope, '[]', TRUE) "
                "ON CONFLICT (role_id) DO NOTHING"
            ),
            {
                "rid": _DEMO_ROLE["role_id"],
                "tid": tenant_id,
                "name": _DEMO_ROLE["name"],
                "perms": _DEMO_ROLE["permissions"],
                "scope": _DEMO_ROLE["data_scope"],
            },
        )
        for dd_id, dd_name in _STANDARD_DATA_DOMAINS:
            # NOTE: standard data domains are NOT auto-seeded anymore — they were
            # dev scaffolding that polluted real tenants. Tenants create their own
            # data domains via the UI. Kept as a no-op loop for backwards clarity.
            pass
        await conn.commit()
    await register_demo(engine, tenant_id)


async def list_for_planning(engine: AsyncEngine, tenant_id: str) -> list[dict[str, Any]]:
    """List all capabilities for a tenant — used by LLM planner for prompt injection.

    Returns lightweight records: capability_id, domain, name, type, input_schema.
    No role filtering — the planner needs full visibility to construct plans.
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT capability_id, domain, name, type, input_schema "
                "FROM business_capabilities WHERE tenant_id = :tid "
                "ORDER BY capability_id"
            ),
            {"tid": tenant_id},
        )
        return [dict(r._mapping) for r in rows]


async def discover(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    role_id: str | None = None,
    query: str | None = None,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Role-aware discovery with optional pgvector semantic search.

    Without a query: return all capabilities (role-filtered if role_id given).
    With a query: pgvector cosine similarity search on capability embedding.
    Falls back to LIKE if embedding column is null for a capability.

    settings is required when query is provided (for Ollama embed + vector dim).
    """
    dim = settings.embedding_dim if settings else 1024
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        if query:
            if settings is None:
                raise ValueError("settings is required for semantic capability discovery")
            from earp_server.knowledge.embedding_service import embed_query

            try:
                q_emb = await embed_query(query)
                emb_str = f"[{', '.join(str(x) for x in q_emb)}]"
                if role_id:
                    rows = await conn.execute(
                        text(
                            f"SELECT c.capability_id, c.domain, c.name, c.type, c.version, c.required_permissions, c.execution, c.status, "
                            f"1 - (c.embedding <=> CAST(:emb AS vector({dim}))) AS similarity "
                            f"FROM business_capabilities c, roles r "
                            f"WHERE c.tenant_id = :tid AND r.role_id = :rid "
                            f"AND c.required_permissions <@ r.permissions "
                            f"ORDER BY c.embedding <=> CAST(:emb2 AS vector({dim})) LIMIT 10"
                        ),
                        {"emb": emb_str, "emb2": emb_str, "tid": tenant_id, "rid": role_id},
                    )
                else:
                    rows = await conn.execute(
                        text(
                            f"SELECT capability_id, domain, name, type, version, "
                            f"1 - (embedding <=> CAST(:emb AS vector({dim}))) AS similarity "
                            f"FROM business_capabilities "
                            f"WHERE tenant_id = :tid "
                            f"ORDER BY embedding <=> CAST(:emb2 AS vector({dim})) LIMIT 10"
                        ),
                        {"emb": emb_str, "emb2": emb_str, "tid": tenant_id},
                    )
                return [dict(r._mapping) for r in rows]
            except Exception:
                logger.warning(
                    "discover: Ollama embedding failed, falling back to exact-match capability lookup",
                    exc_info=True,
                )
                # Fallback: exact match by capability_id (no embedding needed)
                if role_id:
                    rows = await conn.execute(
                        text(
                            "SELECT c.capability_id, c.domain, c.name, c.type, c.version, c.required_permissions, c.execution, c.status "
                            "FROM business_capabilities c, roles r "
                            "WHERE c.tenant_id = :tid AND r.role_id = :rid "
                            "AND c.required_permissions <@ r.permissions "
                            "AND c.capability_id LIKE :qlike"
                        ),
                        {"tid": tenant_id, "rid": role_id, "qlike": f"%{query}%"},
                    )
                else:
                    rows = await conn.execute(
                        text(
                            "SELECT capability_id, domain, name, type, version "
                            "FROM business_capabilities "
                            "WHERE tenant_id = :tid AND capability_id LIKE :qlike"
                        ),
                        {"tid": tenant_id, "qlike": f"%{query}%"},
                    )
                return [dict(r._mapping) for r in rows]
        # no query: return all (role-filtered if role_id given) — use text() + execute()
        if role_id:
            rows = await conn.execute(
                text(
                    "SELECT c.capability_id, c.domain, c.name, c.type, c.version, c.required_permissions, c.execution, c.status "
                    "FROM business_capabilities c, roles r "
                    "WHERE c.tenant_id = :tid AND r.role_id = :rid "
                    "AND c.required_permissions <@ r.permissions"
                ),
                {"tid": tenant_id, "rid": role_id},
            )
        else:
            rows = await conn.execute(
                text(
                    "SELECT capability_id, domain, name, type, version "
                    "FROM business_capabilities WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        return [dict(r._mapping) for r in rows]


# ── Redis Token Bucket Rate Limiter ───────────────────────────────────────────


class TokenBucketRateLimiter:
    """Per-tenant token bucket rate limiter backed by Redis.

    Algorithm: INCR key + EXPIRE on first request in each second window.
    Falls back to pass-through if Redis is unavailable (logged warning).
    """

    def __init__(self, host: str = "localhost", port: int = 6380, rps: int = 100) -> None:
        self._rps = rps
        self._host = host
        self._port = port
        self._redis = None

    async def _ensure_redis(self):
        if self._redis is not None:
            return
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.Redis(host=self._host, port=self._port, socket_connect_timeout=2)
        except Exception:
            logger.warning("Redis unavailable, rate limiter disabled")
            self._redis = False

    async def is_allowed(self, tenant_id: str) -> bool:
        await self._ensure_redis()
        if not self._redis:
            return True  # pass-through on Redis failure
        key = f"rate:{tenant_id}:{int(time.time())}"
        try:
            count = await self._redis.incr(key)  # type: ignore[union-attr]
            if count == 1:
                await self._redis.expire(key, 2)  # type: ignore[union-attr]
            return count <= self._rps
        except Exception:
            logger.warning("Redis rate-limit check failed", exc_info=True)
            return True
