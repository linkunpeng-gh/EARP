"""planner domain public service interface.

M3: Rule-based Data Domain routing alongside existing Business Domain routing
(planner-spec v1.1 §5.1.2; PRD-2026-023 #1).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

__all__: list[str] = ["resolve_data_domains"]


async def resolve_data_domains(
    engine: AsyncEngine,
    tenant_id: str,
    intent: str,
    top_k: int = 3,
) -> list[str]:
    """Rule-based Data Domain routing from user intent.

    Keyword-match the intent against the Business Dictionary data-domain map,
    then intersect with data domains registered and active for this tenant
    (RLS-scoped read). Returns up to top_k domain ids.

    Empty list = "knowledge path disabled for this intent" — callers MUST NOT
    block Business Domain routing when this returns empty (planner-spec §5.1.4).
    """
    from earp_server.knowledge.routing import match_data_domains

    hits = match_data_domains(intent)
    if not hits:
        return []

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text("SELECT data_domain_id FROM data_domains WHERE tenant_id = :tid AND status = 'active'"),
            {"tid": tenant_id},
        )
        registered = {r.data_domain_id for r in rows.fetchall()}

    return [dd for dd in hits[:top_k] if dd in registered]
