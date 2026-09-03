"""Webhook replay, ordering and authoritative-source convergence tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from earp_server.catalog.testing import MockCatalogSourceAdapter
from earp_server.catalog.webhooks import CatalogWebhookError, handle_webhook
from earp_server.infra.db import tenant_session

from .test_catalog_registry import _source


def _signed_event(event_id: str, sequence: int, source: object) -> tuple[bytes, str]:
    body = json.dumps(
        {
            "event_id": event_id,
            "sequence": sequence,
            "occurred_at": datetime.now(UTC).isoformat(),
            "kind": source.kind,
            "stable_id": source.stable_id,
            "version": source.version,
        },
        sort_keys=True,
    ).encode()
    return body, hmac.new(b"secret", body, hashlib.sha256).hexdigest()


async def test_webhook_converges_ref_and_rejects_replay_and_ordering(migrated: str, app_url: str) -> None:
    engine = create_async_engine(app_url, pool_pre_ping=True)
    tenant_id = f"catalog-webhook-{uuid.uuid4().hex[:10]}"
    source = _source()
    adapter = MockCatalogSourceAdapter("test-webhook-source", [source])
    body, signature = _signed_event("event-1", 1, source)
    first = await handle_webhook(
        engine, tenant_id, adapter, secret=b"secret", raw_body=body, supplied_signature=signature
    )
    assert first["status"] == "processed"
    duplicate = await handle_webhook(
        engine, tenant_id, adapter, secret=b"secret", raw_body=body, supplied_signature=signature
    )
    assert duplicate["status"] == "duplicate"
    old_body, old_signature = _signed_event("event-0", 0, source)
    old = await handle_webhook(
        engine, tenant_id, adapter, secret=b"secret", raw_body=old_body, supplied_signature=old_signature
    )
    assert old["status"] == "ignored_out_of_order"
    async with tenant_session(engine, tenant_id) as session:
        rows = await session.execute(
            text("SELECT event_id,status FROM catalog_webhook_events WHERE tenant_id=:tenant ORDER BY sequence_no"),
            {"tenant": tenant_id},
        )
        assert rows.all() == [("event-0", "ignored_out_of_order"), ("event-1", "processed")]
    bad_body, _ = _signed_event("event-bad", 2, source)
    try:
        await handle_webhook(engine, tenant_id, adapter, secret=b"secret", raw_body=bad_body, supplied_signature="bad")
    except CatalogWebhookError as error:
        assert "signature" in str(error)
    else:
        raise AssertionError("invalid webhook signature was accepted")
    await engine.dispose()
