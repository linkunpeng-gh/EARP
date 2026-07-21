"""planner domain public service interface.

M3: Rule-based Data Domain routing alongside existing Business Domain routing.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

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

    Phase 1: stub — returns empty list (knowledge path disabled by default).
    M3 Rule Planner will add Business Dictionary based routing here.
    """
    _ = engine, tenant_id, top_k
    return []
