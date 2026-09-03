"""Catalog Profile configuration persistence; values only, no semantic editing."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.db import tenant_session


class CatalogProfileError(ValueError):
    """A Catalog Profile value configuration is invalid or conflicts."""


def _hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class CatalogProfileService:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        profile_id: str,
        catalog_profile_id: str,
        industry_scope: str,
        enterprise_scope: str,
        data_domain_id: str,
        roles: list[dict[str, Any]],
        backup_approver: str,
    ) -> dict[str, Any]:
        if not idempotency_key.strip():
            raise CatalogProfileError("Idempotency-Key is required")
        if not roles or not backup_approver.strip():
            raise CatalogProfileError("Profile roles and backup approver are required")
        if not any(item.get("role_key") == backup_approver for item in roles):
            raise CatalogProfileError("backup approver must be one of the configured roles")
        payload = {
            "profile_id": profile_id,
            "catalog_profile_id": catalog_profile_id,
            "industry_scope": industry_scope,
            "enterprise_scope": enterprise_scope,
            "data_domain_id": data_domain_id,
            "roles": roles,
            "backup_approver": backup_approver,
        }
        request_hash = _hash(payload)
        async with tenant_session(self._engine, tenant_id) as session:
            existing = (
                (
                    await session.execute(
                        text(
                            "SELECT request_hash,response_body FROM idempotency_records WHERE tenant_id=:tenant "
                            "AND actor_id=:actor AND operation='catalog-profile.create' AND idempotency_key=:key"
                        ),
                        {"tenant": tenant_id, "actor": actor_id, "key": idempotency_key},
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise CatalogProfileError("Idempotency-Key was reused with a different request")
                return {**existing["response_body"], "replayed": True}
            try:
                await session.execute(
                    text(
                        "INSERT INTO catalog_profiles "
                        "(tenant_id,profile_id,catalog_profile_id,profile_schema_version,industry_scope,"
                        "enterprise_scope,data_domain_id,roles,backup_approver,status) VALUES "
                        "(:tenant,:profile,:catalog,'catalog-profile/v2',:industry,:enterprise,:domain,"
                        "CAST(:roles AS jsonb),:backup,'draft')"
                    ),
                    {
                        "tenant": tenant_id,
                        "profile": profile_id,
                        "catalog": catalog_profile_id,
                        "industry": industry_scope,
                        "enterprise": enterprise_scope,
                        "domain": data_domain_id,
                        "roles": json.dumps(roles),
                        "backup": backup_approver,
                    },
                )
            except Exception as error:
                raise CatalogProfileError("Profile ID or catalog_profile_id already exists") from error
            body = {**payload, "profile_schema_version": "catalog-profile/v2", "status": "draft"}
            await session.execute(
                text(
                    "INSERT INTO idempotency_records "
                    "(tenant_id,actor_id,operation,idempotency_key,request_hash,response_status,response_body) "
                    "VALUES (:tenant,:actor,'catalog-profile.create',:key,:hash,201,CAST(:body AS jsonb))"
                ),
                {
                    "tenant": tenant_id,
                    "actor": actor_id,
                    "key": idempotency_key,
                    "hash": request_hash,
                    "body": json.dumps(body),
                },
            )
            await session.execute(
                text(
                    "INSERT INTO catalog_audit_logs "
                    "(tenant_id,audit_id,actor_id,resource_type,resource_id,operation,status,correlation_id,detail) "
                    "VALUES (:tenant,:audit,:actor,'catalog_profile',:resource,'create','succeeded',:correlation,"
                    "CAST(:detail AS jsonb))"
                ),
                {
                    "tenant": tenant_id,
                    "audit": f"caud-{uuid.uuid4().hex[:12]}",
                    "actor": actor_id,
                    "resource": profile_id,
                    "correlation": correlation_id,
                    "detail": json.dumps({"catalog_profile_id": catalog_profile_id}),
                },
            )
            return body
