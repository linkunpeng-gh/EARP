"""Catalog Resolver HTTP boundary; no endpoint exposes cross-tenant existence."""

from __future__ import annotations

import io
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from earp_server.causal_model_management.catalog import CatalogResolutionError, CatalogValidationContext
from earp_server.causal_model_management.schemas import CatalogRef
from earp_server.causal_model_management.service import ActorContext, CausalModelService
from earp_server.infra.db import tenant_session

from .export import CatalogPackExportError, CatalogPackExportService
from .manifests import CatalogManifestError, CatalogManifestService
from .packs import DEFAULT_PACK_VERSION, CatalogPackError, CatalogPackService
from .profiles import CatalogProfileError, CatalogProfileService
from .queries import catalog_metrics, list_approvals, list_manifests, list_packs, list_profiles, list_refs
from .registration import CatalogRegistrationError
from .registry import CatalogRefRegistry
from .webhooks import CatalogWebhookError, handle_webhook

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResolveRequest(StrictModel):
    profile_id: str = Field(min_length=1, max_length=128)
    data_domain_id: str = Field(min_length=1, max_length=64)
    ref: CatalogRef
    expected_kind: str = Field(min_length=1, max_length=32)


class ValidateItem(StrictModel):
    ref: CatalogRef
    expected_kind: str = Field(min_length=1, max_length=32)


class ValidateCatalogRequest(StrictModel):
    profile_id: str = Field(min_length=1, max_length=128)
    data_domain_id: str = Field(min_length=1, max_length=64)
    refs: list[ValidateItem] = Field(min_length=1, max_length=100)


class RegisterRefRequest(StrictModel):
    source_system: str = Field(min_length=1, max_length=64)
    kind: str = Field(min_length=1, max_length=32)
    stable_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)


class RefreshRefRequest(RegisterRefRequest):
    pass


class RevokeRefRequest(RegisterRefRequest):
    reason: str = Field(min_length=1, max_length=4000)


class PackCreateRequest(StrictModel):
    pack_id: str = Field(min_length=1, max_length=128)
    layer: str = Field(pattern="^(platform|industry|enterprise)$")
    name: str = Field(min_length=1, max_length=256)
    owner_role: str = Field(min_length=1, max_length=128)
    version: str = Field(default=DEFAULT_PACK_VERSION, pattern=r"^\d+\.\d+\.\d+$")


class PackEntryRequest(StrictModel):
    pack_id: str = Field(min_length=1, max_length=128)
    pack_version: str = Field(min_length=1, max_length=32, pattern=r"^\d+\.\d+\.\d+$")
    kind: str = Field(min_length=1, max_length=32)
    stable_id: str = Field(min_length=1, max_length=128)
    ref_version: str = Field(min_length=1, max_length=128)


class PackPublishRequest(StrictModel):
    pack_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=32, pattern=r"^\d+\.\d+\.\d+$")
    rationale: str = Field(min_length=1, max_length=4000)


class PackFulfillRequest(StrictModel):
    attempt_id: str = Field(min_length=1, max_length=64)


class ManifestPackSelection(StrictModel):
    pack_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=32, pattern=r"^\d+\.\d+\.\d+$")


class ManifestPreviewRequest(StrictModel):
    profile_id: str = Field(min_length=1, max_length=128)
    manifest_id: str = Field(min_length=1, max_length=128)
    manifest_revision: int = Field(ge=1)
    packs: list[ManifestPackSelection] = Field(min_length=1, max_length=3)


class ManifestActivateRequest(ManifestPreviewRequest):
    expected_active_revision: int | None = Field(default=None, ge=1)
    attestation: dict[str, object]


class ManifestRevokeRequest(StrictModel):
    profile_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=4000)


class ManifestRollbackRequest(StrictModel):
    profile_id: str = Field(min_length=1, max_length=128)
    target_revision: int = Field(ge=1)
    new_manifest_id: str = Field(min_length=1, max_length=128)
    new_revision: int = Field(ge=1)
    attestation: dict[str, object]


class ProfileCreateRequest(StrictModel):
    profile_id: str = Field(min_length=1, max_length=128)
    catalog_profile_id: str = Field(min_length=1, max_length=128)
    industry_scope: str = Field(min_length=1, max_length=128)
    enterprise_scope: str = Field(min_length=1, max_length=128)
    data_domain_id: str = Field(min_length=1, max_length=64)
    roles: list[dict[str, object]] = Field(min_length=1, max_length=32)
    backup_approver: str = Field(min_length=1, max_length=128)


IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


def _pack_error(error: CatalogPackError) -> HTTPException:
    status = 409 if "already exists" in str(error) or "Idempotency-Key" in str(error) else 422
    return HTTPException(status_code=status, detail=str(error))


async def _require_catalog_read(request: Request) -> None:
    """Catalog browse and resolve are protected by the existing RBAC permission."""
    await _require_catalog_permission(request, "ecmc.catalog.read")


async def _require_catalog_permission(request: Request, permission: str) -> None:
    role_id = getattr(request.state, "role_id", "")
    async with tenant_session(request.app.state.engine, request.state.tenant_id) as session:
        row = await session.execute(
            text("SELECT is_admin,permissions FROM roles WHERE tenant_id=:tenant AND role_id=:role"),
            {"tenant": request.state.tenant_id, "role": role_id},
        )
        role = row.mappings().first()
    if role is None or (not role["is_admin"] and permission not in (role["permissions"] or [])):
        raise HTTPException(status_code=403, detail=f"{permission} permission required.")


@router.post("/refs/register", status_code=201)
async def register_ref(body: RegisterRefRequest, request: Request) -> dict[str, object]:
    await _require_catalog_permission(request, "ecmc.catalog.request")
    adapters = getattr(request.app.state, "catalog_source_adapters", {})
    adapter = adapters.get(body.source_system)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Catalog source adapter is not ready.")
    try:
        result = await CatalogRefRegistry(request.app.state.engine).register(
            adapter,
            tenant_id=request.state.tenant_id,
            actor_id=request.state.user_id,
            correlation_id=request.state.n01a_correlation_id,
            kind=body.kind,
            stable_id=body.stable_id,
            version=body.version,
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail="Authoritative source object is unavailable.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Authoritative source verification failed.") from error
    return {
        key: result[key]
        for key in (
            "ref_id",
            "kind",
            "stable_id",
            "version",
            "content_hash",
            "semantic_schema_version",
            "canonicalizer_version",
            "source_system",
            "source_identity",
            "data_domain_id",
            "status",
        )
    }


@router.post("/refs/refresh")
async def refresh_ref(body: RefreshRefRequest, request: Request) -> dict[str, object]:
    await _require_catalog_permission(request, "ecmc.catalog.request")
    adapter = getattr(request.app.state, "catalog_source_adapters", {}).get(body.source_system)
    if adapter is None:
        raise HTTPException(status_code=503, detail="Catalog source adapter is not ready.")
    try:
        result = await CatalogRefRegistry(request.app.state.engine).refresh_from_source(
            adapter,
            tenant_id=request.state.tenant_id,
            actor_id=request.state.user_id,
            correlation_id=request.state.n01a_correlation_id,
            kind=body.kind,
            stable_id=body.stable_id,
            version=body.version,
        )
    except CatalogRegistrationError as error:
        message = str(error)
        status = 404 if "not registered" in message else 409 if "drifted" in message else 422
        raise HTTPException(status_code=status, detail=message) from error
    return {
        key: result[key]
        for key in (
            "ref_id",
            "kind",
            "stable_id",
            "version",
            "content_hash",
            "status",
            "source_system",
            "source_identity",
            "data_domain_id",
        )
    }


@router.post("/refs/revoke")
async def revoke_ref(
    body: RevokeRefRequest, request: Request, idempotency_key: IdempotencyKey
) -> dict[str, object]:
    await _require_catalog_permission(request, "ecmc.catalog.request")
    try:
        return await CatalogRefRegistry(request.app.state.engine).revoke(
            tenant_id=request.state.tenant_id,
            actor_id=request.state.user_id,
            correlation_id=request.state.n01a_correlation_id,
            idempotency_key=idempotency_key,
            **body.model_dump(),
        )
    except CatalogRegistrationError as error:
        message = str(error)
        status = 404 if "not registered" in message else 409 if "Idempotency" in message else 422
        raise HTTPException(status_code=status, detail=message) from error


@router.post("/webhooks/{source_system}")
async def catalog_webhook(source_system: str, request: Request) -> dict[str, object]:
    """Receive a signed source event; content is always re-read from the source."""
    adapter = getattr(request.app.state, "catalog_source_adapters", {}).get(source_system)
    secret = getattr(request.app.state, "catalog_webhook_secrets", {}).get(source_system)
    if adapter is None or not secret:
        raise HTTPException(status_code=503, detail="Catalog webhook source is not ready.")
    try:
        result = await handle_webhook(
            request.app.state.engine,
            request.state.tenant_id,
            adapter,
            secret=secret.encode() if isinstance(secret, str) else secret,
            raw_body=await request.body(),
            supplied_signature=request.headers.get("X-Catalog-Signature", ""),
        )
    except CatalogWebhookError as error:
        status = 409 if "replay" in str(error) or "ordering" in str(error) else 422
        raise HTTPException(status_code=status, detail=str(error)) from error
    return result


@router.post("/packs", status_code=201)
async def create_pack_draft(
    body: PackCreateRequest, request: Request, idempotency_key: IdempotencyKey
) -> dict[str, object]:
    await _require_catalog_permission(request, "ecmc.catalog.request")
    try:
        return await CatalogPackService(request.app.state.engine).create_draft(
            tenant_id=request.state.tenant_id,
            actor_id=request.state.user_id,
            pack_id=body.pack_id,
            version=body.version,
            layer=body.layer,
            name=body.name,
            owner_role=body.owner_role,
            idempotency_key=idempotency_key,
        )
    except CatalogPackError as error:
        raise _pack_error(error) from error


@router.post("/packs/entries", status_code=201)
async def add_pack_entry(
    body: PackEntryRequest, request: Request, idempotency_key: IdempotencyKey
) -> dict[str, object]:
    await _require_catalog_permission(request, "ecmc.catalog.request")
    try:
        return await CatalogPackService(request.app.state.engine).add_registered_entry(
            tenant_id=request.state.tenant_id,
            actor_id=request.state.user_id,
            pack_id=body.pack_id,
            pack_version=body.pack_version,
            kind=body.kind,
            stable_id=body.stable_id,
            version=body.ref_version,
            idempotency_key=idempotency_key,
        )
    except CatalogPackError as error:
        raise _pack_error(error) from error


@router.post("/packs/publish-requests", status_code=201)
async def create_pack_publish_request(
    body: PackPublishRequest, request: Request, idempotency_key: IdempotencyKey
) -> dict[str, object]:
    await _require_catalog_permission(request, "ecmc.catalog.request")
    try:
        return await CatalogPackService(request.app.state.engine).create_publish_request(
            tenant_id=request.state.tenant_id,
            actor_id=request.state.user_id,
            correlation_id=request.state.n01a_correlation_id,
            pack_id=body.pack_id,
            version=body.version,
            rationale=body.rationale,
            idempotency_key=idempotency_key,
        )
    except CatalogPackError as error:
        raise _pack_error(error) from error


@router.post("/packs/publish-requests/{request_id}/fulfill")
async def fulfill_pack_publish(
    request_id: str, body: PackFulfillRequest, request: Request, idempotency_key: IdempotencyKey
) -> dict[str, object]:
    result = await CausalModelService(
        request.app.state.engine, request.app.state.n01a_catalog_resolver
    ).fulfill_pack_publish(
        ActorContext(
            tenant_id=request.state.tenant_id,
            actor_id=request.state.user_id,
            role_id=request.state.role_id,
            correlation_id=request.state.n01a_correlation_id,
        ),
        request_id,
        body.attempt_id,
        idempotency_key,
    )
    return result["body"]


@router.get("/packs/{pack_id}/{version}/export")
async def export_pack(pack_id: str, version: str, request: Request) -> StreamingResponse:
    await _require_catalog_read(request)
    async with tenant_session(request.app.state.engine, request.state.tenant_id) as session:
        role = (
            await session.execute(
                text("SELECT is_admin FROM roles WHERE tenant_id=:tenant AND role_id=:role"),
                {"tenant": request.state.tenant_id, "role": request.state.role_id},
            )
        ).scalar_one_or_none()
    try:
        archive = await CatalogPackExportService(request.app.state.engine).export(
            tenant_id=request.state.tenant_id,
            actor_role=request.state.role_id,
            is_platform_admin=bool(role),
            pack_id=pack_id,
            version=version,
            adapters=getattr(request.app.state, "catalog_source_adapters", {}),
        )
    except CatalogPackExportError as error:
        message = str(error)
        status = 403 if "only the Pack owner" in message else 503 if "adapter" in message else 409
        raise HTTPException(status_code=status, detail=message) from error
    return StreamingResponse(
        io.BytesIO(archive),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{pack_id}-{version}.earppack"'},
    )


@router.post("/manifests/preview")
async def preview_manifest(body: ManifestPreviewRequest, request: Request) -> dict[str, object]:
    await _require_catalog_permission(request, "ecmc.catalog.manifest.publish")
    try:
        return await CatalogManifestService(request.app.state.engine).build_from_packs(
            tenant_id=request.state.tenant_id,
            profile_id=body.profile_id,
            manifest_id=body.manifest_id,
            manifest_revision=body.manifest_revision,
            packs=[item.model_dump() for item in body.packs],
        )
    except CatalogManifestError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/manifests/activate")
async def activate_manifest(
    body: ManifestActivateRequest, request: Request, idempotency_key: IdempotencyKey
) -> dict[str, object]:
    await _require_catalog_permission(request, "ecmc.catalog.manifest.publish")
    service = CatalogManifestService(request.app.state.engine)
    try:
        manifest = await service.build_from_packs(
            tenant_id=request.state.tenant_id,
            profile_id=body.profile_id,
            manifest_id=body.manifest_id,
            manifest_revision=body.manifest_revision,
            packs=[item.model_dump() for item in body.packs],
        )
        digest = await service.publish_and_activate(
            tenant_id=request.state.tenant_id,
            profile_id=body.profile_id,
            actor_id=request.state.user_id,
            correlation_id=request.state.n01a_correlation_id,
            idempotency_key=idempotency_key,
            manifest=manifest,
            attestation=body.attestation,
            expected_active_revision=body.expected_active_revision,
        )
    except CatalogManifestError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"manifest_hash": digest, "status": "active"}


@router.post("/manifests/revoke")
async def revoke_manifest(
    body: ManifestRevokeRequest, request: Request, idempotency_key: IdempotencyKey
) -> dict[str, object]:
    await _require_catalog_permission(request, "ecmc.catalog.manifest.publish")
    try:
        return await CatalogManifestService(request.app.state.engine).revoke_active(
            tenant_id=request.state.tenant_id,
            profile_id=body.profile_id,
            actor_id=request.state.user_id,
            correlation_id=request.state.n01a_correlation_id,
            idempotency_key=idempotency_key,
            reason=body.reason,
        )
    except CatalogManifestError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/manifests/rollback")
async def rollback_manifest(
    body: ManifestRollbackRequest, request: Request, idempotency_key: IdempotencyKey
) -> dict[str, object]:
    await _require_catalog_permission(request, "ecmc.catalog.manifest.publish")
    try:
        digest = await CatalogManifestService(request.app.state.engine).rollback(
            tenant_id=request.state.tenant_id,
            profile_id=body.profile_id,
            target_revision=body.target_revision,
            new_manifest_id=body.new_manifest_id,
            new_revision=body.new_revision,
            actor_id=request.state.user_id,
            correlation_id=request.state.n01a_correlation_id,
            idempotency_key=idempotency_key,
            attestation=body.attestation,
        )
    except CatalogManifestError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return {"manifest_hash": digest, "status": "active", "revision": body.new_revision}


@router.get("/refs")
async def refs(
    request: Request,
    kind: str | None = Query(default=None, max_length=32),
    status: str | None = Query(default=None, max_length=24),
    q: str | None = Query(default=None, max_length=128),
) -> dict[str, list[dict]]:
    await _require_catalog_read(request)
    return {
        "items": await list_refs(
            request.app.state.engine,
            request.state.tenant_id,
            kind=kind,
            status=status,
            query=q,
        )
    }


@router.get("/packs")
async def packs(request: Request) -> dict[str, list[dict]]:
    await _require_catalog_read(request)
    return {"items": await list_packs(request.app.state.engine, request.state.tenant_id)}


@router.get("/manifests")
async def manifests(request: Request) -> dict[str, list[dict]]:
    await _require_catalog_read(request)
    return {"items": await list_manifests(request.app.state.engine, request.state.tenant_id)}


@router.get("/profiles")
async def profiles(request: Request) -> dict[str, list[dict]]:
    await _require_catalog_read(request)
    return {"items": await list_profiles(request.app.state.engine, request.state.tenant_id)}


@router.post("/profiles", status_code=201)
async def create_profile(
    body: ProfileCreateRequest, request: Request, idempotency_key: IdempotencyKey
) -> dict[str, object]:
    await _require_catalog_permission(request, "ecmc.catalog.request")
    try:
        return await CatalogProfileService(request.app.state.engine).create(
            tenant_id=request.state.tenant_id,
            actor_id=request.state.user_id,
            correlation_id=request.state.n01a_correlation_id,
            idempotency_key=idempotency_key,
            **body.model_dump(),
        )
    except CatalogProfileError as error:
        status = 409 if "already" in str(error) or "Idempotency" in str(error) else 422
        raise HTTPException(status_code=status, detail=str(error)) from error


@router.get("/approvals")
async def approvals(request: Request) -> dict[str, list[dict]]:
    await _require_catalog_read(request)
    return {"items": await list_approvals(request.app.state.engine, request.state.tenant_id)}


@router.get("/metrics")
async def metrics(request: Request) -> dict[str, object]:
    await _require_catalog_read(request)
    return await catalog_metrics(request.app.state.engine, request.state.tenant_id)


def _context(request: Request, data_domain_id: str, profile_id: str) -> CatalogValidationContext:
    return CatalogValidationContext(request.state.tenant_id, data_domain_id, {"profile_id": profile_id})


def _not_visible(error: CatalogResolutionError) -> HTTPException:
    """Map every frozen Resolver denial to non-enumerable 404 semantics."""
    return HTTPException(status_code=404, detail={"code": error.code, "message": "Catalog reference unavailable."})


@router.post("/resolve")
async def resolve(body: ResolveRequest, request: Request) -> dict:
    await _require_catalog_read(request)
    try:
        resolved = await request.app.state.n01a_catalog_resolver.resolve(
            request.state.tenant_id,
            body.ref,
            body.expected_kind,
            context=_context(request, body.data_domain_id, body.profile_id),
        )
    except CatalogResolutionError as error:
        raise _not_visible(error) from error
    return {
        "kind": resolved.kind,
        "stable_id": resolved.stable_id,
        "version": resolved.version,
        "content_hash": resolved.content_hash,
        "status": resolved.status,
        "data_domain_id": resolved.data_domain_id,
        "semantic_schema_version": resolved.semantic_schema_version,
        "compatibility_metadata": resolved.compatibility_metadata,
    }


@router.post("/validate")
async def validate(body: ValidateCatalogRequest, request: Request) -> dict:
    await _require_catalog_read(request)
    context = _context(request, body.data_domain_id, body.profile_id)
    result = await request.app.state.n01a_catalog_resolver.validate(
        request.state.tenant_id,
        [(item.ref, item.expected_kind) for item in body.refs],
        context,
    )
    return {
        "resolved": [item.pin() for item in result.resolved],
        "issues": [
            {"code": error.code, "stable_id": error.ref.stable_id, "version": error.ref.version}
            for error in result.errors
        ],
    }
