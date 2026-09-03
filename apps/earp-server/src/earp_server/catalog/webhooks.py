"""Signed Catalog webhook intake with persistent replay/order evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session

from .hashing import CatalogCanonicalizationError, content_hash
from .registration import CatalogRegistrationError
from .registry import CatalogRefRegistry
from .source import SourceAdapter, webhook_signature_valid


class CatalogWebhookError(ValueError):
    """A webhook is invalid, replayed, stale or cannot converge safely."""


def validate_webhook_envelope(
    *, secret: bytes, raw_body: bytes, supplied_signature: str, max_age_seconds: int = 300
) -> dict[str, Any]:
    if not webhook_signature_valid(secret, raw_body, supplied_signature):
        raise CatalogWebhookError("webhook signature is invalid")
    try:
        event = json.loads(raw_body)
        occurred_at = datetime.fromisoformat(str(event["occurred_at"]).replace("Z", "+00:00"))
        int(event["sequence"])
        for field in ("event_id", "kind", "stable_id", "version"):
            if not str(event[field]).strip():
                raise KeyError(field)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise CatalogWebhookError("webhook envelope is invalid") from error
    if occurred_at.tzinfo is None:
        raise CatalogWebhookError("webhook occurred_at must include timezone")
    age = datetime.now(UTC) - occurred_at.astimezone(UTC)
    if age < -timedelta(seconds=30) or age > timedelta(seconds=max_age_seconds):
        raise CatalogWebhookError("webhook is outside the replay protection window")
    return event


async def handle_webhook(
    engine: AsyncEngine,
    tenant_id: str,
    adapter: SourceAdapter,
    *,
    secret: bytes,
    raw_body: bytes,
    supplied_signature: str,
) -> dict[str, object]:
    """Accept one signed event, then re-read the exact object from the source.

    Event payloads carry only an exact reference locator. They never supply
    semantic content, lifecycle status or a client-provided hash.
    """
    event = validate_webhook_envelope(secret=secret, raw_body=raw_body, supplied_signature=supplied_signature)
    source_system = adapter.source_system.strip()
    event_id = str(event["event_id"])
    sequence_no = int(event["sequence"])
    payload_hash = hashlib.sha256(raw_body).hexdigest()
    async with tenant_session(engine, tenant_id) as session:
        existing = (
            (
                await session.execute(
                    text(
                        "SELECT payload_hash,status FROM catalog_webhook_events WHERE tenant_id=:tenant "
                        "AND source_system=:source AND event_id=:event"
                    ),
                    {"tenant": tenant_id, "source": source_system, "event": event_id},
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            if existing["payload_hash"] != payload_hash:
                raise CatalogWebhookError("webhook event_id was reused with a different payload")
            return {"event_id": event_id, "status": "duplicate", "replayed": True}
        latest = (
            await session.execute(
                text(
                    "SELECT max(sequence_no) FROM catalog_webhook_events "
                    "WHERE tenant_id=:tenant AND source_system=:source"
                ),
                {"tenant": tenant_id, "source": source_system},
            )
        ).scalar_one()
        if latest is not None and sequence_no <= int(latest):
            await session.execute(
                text(
                    "INSERT INTO catalog_webhook_events "
                    "(tenant_id,source_system,event_id,sequence_no,payload_hash,status,error_code) "
                    "VALUES (:tenant,:source,:event,:sequence,:hash,'ignored_out_of_order','OUT_OF_ORDER')"
                ),
                {
                    "tenant": tenant_id,
                    "source": source_system,
                    "event": event_id,
                    "sequence": sequence_no,
                    "hash": payload_hash,
                },
            )
            return {"event_id": event_id, "status": "ignored_out_of_order", "replayed": False}
        await session.execute(
            text(
                "INSERT INTO catalog_webhook_events "
                "(tenant_id,source_system,event_id,sequence_no,payload_hash,status) "
                "VALUES (:tenant,:source,:event,:sequence,:hash,'accepted')"
            ),
            {
                "tenant": tenant_id,
                "source": source_system,
                "event": event_id,
                "sequence": sequence_no,
                "hash": payload_hash,
            },
        )
    try:
        source = await adapter.fetch_exact(str(event["kind"]), str(event["stable_id"]), str(event["version"]))
        # Verify the source-owned object before touching a CatalogRef.
        content_hash(source.canonical_input, schema_version=source.schema_version)
        registry = CatalogRefRegistry(engine)
        try:
            result = await registry.refresh_from_source(
                adapter,
                tenant_id=tenant_id,
                actor_id="catalog-webhook",
                correlation_id=event_id,
                kind=source.kind,
                stable_id=source.stable_id,
                version=source.version,
            )
        except CatalogRegistrationError as error:
            if "not registered" not in str(error):
                raise
            result = await registry.register(
                adapter,
                tenant_id=tenant_id,
                actor_id="catalog-webhook",
                correlation_id=event_id,
                kind=source.kind,
                stable_id=source.stable_id,
                version=source.version,
            )
    except (CatalogCanonicalizationError, CatalogRegistrationError, LookupError, ValueError) as error:
        status = "failed"
        error_code = "SOURCE_VERIFICATION_FAILED"
        async with tenant_session(engine, tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE catalog_webhook_events SET status=:status,error_code=:error,processed_at=now() "
                    "WHERE tenant_id=:tenant AND source_system=:source AND event_id=:event"
                ),
                {
                    "status": status,
                    "error": error_code,
                    "tenant": tenant_id,
                    "source": source_system,
                    "event": event_id,
                },
            )
        raise CatalogWebhookError(str(error)) from error
    async with tenant_session(engine, tenant_id) as session:
        await session.execute(
            text(
                "UPDATE catalog_webhook_events SET status='processed',processed_at=now() "
                "WHERE tenant_id=:tenant AND source_system=:source AND event_id=:event"
            ),
            {"tenant": tenant_id, "source": source_system, "event": event_id},
        )
    return {"event_id": event_id, "status": "processed", "replayed": False, "ref_id": result["ref_id"]}
