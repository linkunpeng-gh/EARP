"""Draft-only Pack editing and immutable Pack-version publication."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from earp_server.infra.db import tenant_session

from .domain import CatalogCompositionError, pack_content_hash


class CatalogPackError(ValueError):
    """A Pack lifecycle operation violates the Phase 1 contract."""


DEFAULT_PACK_VERSION = "1.0.0"
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _request_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class CatalogPackService:
    """Manage Pack reference pins without accepting semantic object payloads."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create_draft(
        self,
        *,
        tenant_id: str,
        actor_id: str = "internal",
        pack_id: str,
        version: str = DEFAULT_PACK_VERSION,
        layer: str,
        name: str,
        owner_role: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if not _SEMVER.fullmatch(version):
            raise CatalogPackError("Pack version must use semantic versioning, for example 1.0.0")
        payload = {
            "pack_id": pack_id,
            "version": version,
            "layer": layer,
            "name": name,
            "owner_role": owner_role,
        }
        async with tenant_session(self._engine, tenant_id) as session:
            replay = await self._replay(session, tenant_id, actor_id, "catalog-pack.create", idempotency_key, payload)
            if replay is not None:
                return replay
            try:
                await session.execute(
                    text(
                        "INSERT INTO catalog_packs "
                        "(tenant_id,pack_id,version,layer,name,owner_role,status) VALUES "
                        "(:tenant,:pack_id,:version,:layer,:name,:owner_role,'draft')"
                    ),
                    {
                        "tenant": tenant_id,
                        "pack_id": pack_id,
                        "version": version,
                        "layer": layer,
                        "name": name,
                        "owner_role": owner_role,
                    },
                )
            except Exception as error:
                raise CatalogPackError("Pack version already exists or is invalid") from error
            body = {**payload, "status": "draft"}
            await self._remember(session, tenant_id, actor_id, "catalog-pack.create", idempotency_key, payload, body)
            return body

    async def add_registered_entry(
        self,
        *,
        tenant_id: str,
        actor_id: str = "internal",
        pack_id: str,
        pack_version: str,
        kind: str,
        stable_id: str,
        version: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Pin an already registered exact ref; client hash and payload are absent."""
        payload = {
            "pack_id": pack_id,
            "pack_version": pack_version,
            "kind": kind,
            "stable_id": stable_id,
            "version": version,
        }
        async with tenant_session(self._engine, tenant_id) as session:
            replay = await self._replay(
                session, tenant_id, actor_id, "catalog-pack.entry.add", idempotency_key, payload
            )
            if replay is not None:
                return replay
            pack = await session.execute(
                text(
                    "SELECT status FROM catalog_packs WHERE tenant_id=:tenant AND pack_id=:pack_id AND version=:version"
                ),
                {"tenant": tenant_id, "pack_id": pack_id, "version": pack_version},
            )
            if pack.scalar_one_or_none() != "draft":
                raise CatalogPackError("only draft Pack versions may be edited")
            ref = await session.execute(
                text(
                    "SELECT content_hash,status FROM catalog_refs WHERE tenant_id=:tenant AND kind=:kind "
                    "AND stable_id=:stable_id AND version=:version AND deleted_at IS NULL"
                ),
                {
                    "tenant": tenant_id,
                    "kind": kind,
                    "stable_id": stable_id,
                    "version": version,
                },
            )
            pin = ref.mappings().first()
            if pin is None or pin["status"] == "inactive":
                raise CatalogPackError("only registered non-inactive exact refs may enter a Pack")
            await session.execute(
                text(
                    "INSERT INTO catalog_pack_entries "
                    "(tenant_id,pack_id,pack_version,kind,stable_id,version,content_hash) VALUES "
                    "(:tenant,:pack_id,:pack_version,:kind,:stable_id,:version,:content_hash) "
                    "ON CONFLICT (tenant_id,pack_id,pack_version,kind,stable_id,version) "
                    "DO NOTHING"
                ),
                {
                    "tenant": tenant_id,
                    "pack_id": pack_id,
                    "pack_version": pack_version,
                    "kind": kind,
                    "stable_id": stable_id,
                    "version": version,
                    "content_hash": pin["content_hash"],
                },
            )
            body = {**payload, "status": "pinned", "content_hash": pin["content_hash"]}
            await self._remember(session, tenant_id, actor_id, "catalog-pack.entry.add", idempotency_key, payload, body)
            return body

    async def publish(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        correlation_id: str,
        pack_id: str,
        version: str,
    ) -> str:
        """Freeze a draft Pack version after calculating its authoritative Pack hash."""
        async with tenant_session(self._engine, tenant_id) as session:
            pack = await session.execute(
                text(
                    "SELECT layer,status FROM catalog_packs WHERE tenant_id=:tenant "
                    "AND pack_id=:pack_id AND version=:version"
                ),
                {"tenant": tenant_id, "pack_id": pack_id, "version": version},
            )
            row = pack.mappings().first()
            if row is None:
                raise CatalogPackError("Pack version is not found")
            if row["status"] != "draft":
                raise CatalogPackError("published Pack versions are immutable")
            entries = await session.execute(
                text(
                    "SELECT kind,stable_id,version,content_hash FROM catalog_pack_entries "
                    "WHERE tenant_id=:tenant AND pack_id=:pack_id AND pack_version=:version"
                ),
                {"tenant": tenant_id, "pack_id": pack_id, "version": version},
            )
            pins = [dict(item) for item in entries.mappings()]
            try:
                digest = pack_content_hash(pack_id, row["layer"], version, pins)
            except CatalogCompositionError as error:
                raise CatalogPackError(str(error)) from error
            published = await session.execute(
                text(
                    "UPDATE catalog_packs SET content_hash=:content_hash,status='published',published_at=now() "
                    "WHERE tenant_id=:tenant AND pack_id=:pack_id AND version=:version AND status='draft' "
                    "RETURNING content_hash"
                ),
                {
                    "tenant": tenant_id,
                    "pack_id": pack_id,
                    "version": version,
                    "content_hash": digest,
                },
            )
            if published.scalar_one_or_none() is None:
                raise CatalogPackError("Pack publication conflicted; retry from current state")
            await session.execute(
                text(
                    "INSERT INTO catalog_audit_logs "
                    "(tenant_id,audit_id,actor_id,resource_type,resource_id,operation,after_hash,status,"
                    "correlation_id,detail) VALUES "
                    "(:tenant,:audit_id,:actor,'catalog_pack',:resource_id,'publish',:after_hash,"
                    "'succeeded',:correlation_id,CAST(:detail AS jsonb))"
                ),
                {
                    "tenant": tenant_id,
                    "audit_id": f"caud-{uuid.uuid4().hex[:12]}",
                    "actor": actor_id,
                    "resource_id": f"{pack_id}@{version}",
                    "after_hash": digest,
                    "correlation_id": correlation_id,
                    "detail": json.dumps({"layer": row["layer"]}),
                },
            )
            return digest

    async def create_publish_request(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        correlation_id: str,
        pack_id: str,
        version: str,
        rationale: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Create a Pack publish request in the shared N01A approval state machine."""
        if not rationale.strip():
            raise CatalogPackError("publish rationale is required")
        payload = {
            "pack_id": pack_id,
            "version": version,
            "rationale": rationale,
        }
        operation = "catalog-pack.publish-request.create"
        async with tenant_session(self._engine, tenant_id) as session:
            replay = await self._replay(session, tenant_id, actor_id, operation, idempotency_key, payload)
            if replay is not None:
                return replay
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT status,owner_role FROM catalog_packs "
                            "WHERE tenant_id=:tenant AND pack_id=:pack_id AND version=:version"
                        ),
                        {"tenant": tenant_id, "pack_id": pack_id, "version": version},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise CatalogPackError("Pack version is not found")
            if row["status"] != "draft":
                raise CatalogPackError("only draft Pack versions may be submitted for publication")
            request_id = f"ccr-{uuid.uuid4().hex[:16]}"
            resource_id = f"{pack_id}@{version}"
            await session.execute(
                text(
                    "INSERT INTO catalog_change_requests "
                    "(tenant_id,request_id,request_type,target_data_domain_ref,rationale,"
                    "proposed_definition,status,requester_id,idempotency_key,resource_type,resource_id) "
                    "VALUES (:tenant,:request,'pack_publish',CAST(:target AS jsonb),:rationale,"
                    "CAST(:definition AS jsonb),'draft',:actor,:key,'catalog_pack',:resource)"
                ),
                {
                    "tenant": tenant_id,
                    "request": request_id,
                    "target": json.dumps({"resource_type": "catalog_pack", "resource_id": resource_id}),
                    "rationale": rationale,
                    "definition": json.dumps({"kind": "pack_publish", **payload}),
                    "actor": actor_id,
                    "key": idempotency_key,
                    "resource": resource_id,
                },
            )
            body = {
                "request_id": request_id,
                "request_type": "pack_publish",
                "resource_type": "catalog_pack",
                "resource_id": resource_id,
                "status": "draft",
                "revision": 1,
                **payload,
            }
            await session.execute(
                text(
                    "INSERT INTO catalog_audit_logs "
                    "(tenant_id,audit_id,actor_id,resource_type,resource_id,operation,status,"
                    "reason,correlation_id,detail) VALUES "
                    "(:tenant,:audit,:actor,'catalog_pack',:resource,'request_publish','succeeded',"
                    ":reason,:correlation,CAST(:detail AS jsonb))"
                ),
                {
                    "tenant": tenant_id,
                    "audit": f"caud-{uuid.uuid4().hex[:12]}",
                    "actor": actor_id,
                    "resource": resource_id,
                    "reason": rationale,
                    "correlation": correlation_id,
                    "detail": json.dumps({"request_id": request_id, "owner_role": row["owner_role"]}),
                },
            )
            await self._remember(session, tenant_id, actor_id, operation, idempotency_key, payload, body)
            return body

    @staticmethod
    async def _replay(
        session: AsyncSession,
        tenant_id: str,
        actor_id: str,
        operation: str,
        idempotency_key: str | None,
        payload: Any,
    ) -> dict[str, object] | None:
        if idempotency_key is None:
            return None
        if not idempotency_key.strip():
            raise CatalogPackError("Idempotency-Key is required")
        row = await session.execute(
            text(
                "SELECT request_hash,response_body FROM idempotency_records "
                "WHERE tenant_id=:tenant AND actor_id=:actor AND operation=:operation AND idempotency_key=:key"
            ),
            {
                "tenant": tenant_id,
                "actor": actor_id,
                "operation": operation,
                "key": idempotency_key,
            },
        )
        found = row.mappings().first()
        if found is None:
            return None
        if found["request_hash"] != _request_hash(payload):
            raise CatalogPackError("Idempotency-Key was reused with a different request")
        return dict(found["response_body"])

    @staticmethod
    async def _remember(
        session: AsyncSession,
        tenant_id: str,
        actor_id: str,
        operation: str,
        idempotency_key: str | None,
        payload: Any,
        body: Any,
    ) -> None:
        if idempotency_key is None:
            return
        await session.execute(
            text(
                "INSERT INTO idempotency_records "
                "(tenant_id,actor_id,operation,idempotency_key,request_hash,response_status,response_body) "
                "VALUES (:tenant,:actor,:operation,:key,:hash,201,CAST(:body AS jsonb))"
            ),
            {
                "tenant": tenant_id,
                "actor": actor_id,
                "operation": operation,
                "key": idempotency_key,
                "hash": _request_hash(payload),
                "body": json.dumps(body, ensure_ascii=False),
            },
        )
