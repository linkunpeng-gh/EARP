"""Audit consumer: subscribes to EventBus and writes audit_logs rows.

Registered at app startup (main.py lifespan). Runs as background task — does NOT
block the invoke response path (EventBus fire-and-forget).
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.eventbus import CloudEvent

logger = logging.getLogger(__name__)


def audit_handler_factory(engine: AsyncEngine):
    async def handler(event: CloudEvent) -> None:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{event.tenant_id}'"))
            await conn.execute(
                text(
                    "INSERT INTO audit_logs (tenant_id, event_type, entity_type, entity_id, user_id, detail) "
                    "VALUES (:tid, :etype, :entity_type, :entity_id, :uid, :detail)"
                ),
                {
                    "tid": event.tenant_id,
                    "etype": event.type,
                    "entity_type": event.data.get("entity_type", ""),
                    "entity_id": event.data.get("entity_id", ""),
                    "uid": event.data.get("user_id", ""),
                    "detail": json.dumps(event.data),
                },
            )
            await conn.commit()
        logger.debug("audit: %s tenant=%s", event.type, event.tenant_id)

    return handler
