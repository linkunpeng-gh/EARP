"""Fail-closed runtime Resolver for an already verified active Manifest."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from earp_server.causal_model_management.catalog import (
    CatalogResolutionError,
    CatalogValidationContext,
    CatalogValidationResult,
    ResolvedCatalogRef,
)
from earp_server.causal_model_management.schemas import CatalogRef

from .domain import CatalogCompositionError, validate_manifest_for_activation


class ManifestCatalogResolver:
    """Resolver with active-generation cache invalidation and no fallback source."""

    def __init__(
        self,
        active: Callable[[str], tuple[int, dict[str, Any], dict[str, Any]] | None],
        source_hash: Callable[[str, dict[str, Any]], str | None],
    ) -> None:
        self._active = active
        self._source_hash = source_hash
        self._cache: dict[tuple[str, int, str, str, str], ResolvedCatalogRef] = {}

    async def resolve(
        self,
        tenant_id: str,
        ref: CatalogRef,
        expected_kind: str,
        *,
        at_version: str | None = None,
        context: CatalogValidationContext | None = None,
    ) -> ResolvedCatalogRef:
        if ref.kind != expected_kind:
            raise CatalogResolutionError("CATALOG_REF_KIND_MISMATCH", ref, "CatalogRef kind does not match its use.")
        if at_version is not None and at_version != ref.version:
            raise CatalogResolutionError("CATALOG_REF_NOT_FOUND", ref, "CatalogRef version is not exact.")
        current = self._active(tenant_id)
        if current is None:
            raise CatalogResolutionError("CATALOG_REF_NOT_FOUND", ref, "No active signed Catalog manifest.")
        generation, manifest, attestation = current
        try:
            validate_manifest_for_activation(manifest, attestation)
        except CatalogCompositionError as error:
            raise CatalogResolutionError(
                "CATALOG_REF_NOT_FOUND", ref, "Active Catalog manifest is unavailable."
            ) from error
        key = (tenant_id, generation, ref.kind, ref.stable_id, ref.version)
        cached = self._cache.get(key)
        if cached is not None:
            # The cache is keyed by active generation, but a source-index hash
            # drift can occur without a Manifest activation. Re-check the
            # authoritative pin before serving a cached result.
            if self._source_hash(tenant_id, cached.pin()) != cached.content_hash:
                raise CatalogResolutionError(
                    "CATALOG_REF_NOT_FOUND", ref, "CatalogRef content hash drifted; resolution blocked."
                )
            return self._context_gate(cached, ref, context)
        entry = next((item for item in manifest.get("entries", []) if self._matches(item, ref)), None)
        if entry is None:
            raise CatalogResolutionError("CATALOG_REF_NOT_FOUND", ref, "CatalogRef is absent from the active manifest.")
        if entry.get("status") != "active":
            raise CatalogResolutionError("CATALOG_REF_INACTIVE", ref, "CatalogRef is not active for new use.")
        if self._source_hash(tenant_id, entry) != entry.get("content_hash"):
            raise CatalogResolutionError(
                "CATALOG_REF_NOT_FOUND", ref, "CatalogRef content hash drifted; resolution blocked."
            )
        resolved = ResolvedCatalogRef(
            kind=ref.kind,
            stable_id=ref.stable_id,
            version=ref.version,
            content_hash=str(entry["content_hash"]),
            status=str(entry["status"]),
            data_domain_id=str(entry["data_domain_id"]),
            semantic_schema_version=str(entry["semantic_schema_version"]),
            display_name=entry.get("display_name"),
            input_schema=entry.get("input_schema"),
            output_schema=entry.get("output_schema"),
            compatibility_metadata=entry.get("compatibility_metadata", {}),
        )
        self._cache[key] = resolved
        return self._context_gate(resolved, ref, context)

    def _context_gate(
        self, resolved: ResolvedCatalogRef, ref: CatalogRef, context: CatalogValidationContext | None
    ) -> ResolvedCatalogRef:
        if context is not None and resolved.data_domain_id != context.data_domain_id:
            raise CatalogResolutionError(
                "CATALOG_REF_DOMAIN_FORBIDDEN", ref, "CatalogRef is outside the allowed data domain."
            )
        return resolved

    @staticmethod
    def _matches(entry: dict[str, Any], ref: CatalogRef) -> bool:
        return (entry.get("kind"), entry.get("stable_id"), entry.get("version")) == (
            ref.kind,
            ref.stable_id,
            ref.version,
        )

    async def validate(
        self,
        tenant_id: str,
        refs: list[tuple[CatalogRef, str]],
        context: CatalogValidationContext,
    ) -> CatalogValidationResult:
        resolved: list[ResolvedCatalogRef] = []
        errors: list[CatalogResolutionError] = []
        for ref, expected_kind in refs:
            try:
                resolved.append(await self.resolve(tenant_id, ref, expected_kind, context=context))
            except CatalogResolutionError as error:
                errors.append(error)
        return CatalogValidationResult(tuple(resolved), tuple(errors))
