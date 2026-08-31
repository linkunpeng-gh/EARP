"""CatalogResolver contract and deterministic test adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .schemas import CatalogRef

CATALOG_ERROR_CODES = frozenset(
    {
        "CATALOG_REF_NOT_FOUND",
        "CATALOG_REF_INACTIVE",
        "CATALOG_REF_KIND_MISMATCH",
        "CATALOG_REF_DOMAIN_FORBIDDEN",
        "CATALOG_REF_SCHEMA_INCOMPATIBLE",
    }
)


@dataclass(frozen=True)
class CatalogResolutionError(ValueError):
    code: str
    ref: CatalogRef
    message: str

    def __post_init__(self) -> None:
        if self.code not in CATALOG_ERROR_CODES:
            raise ValueError(f"unsupported catalog error code: {self.code}")


@dataclass(frozen=True)
class ResolvedCatalogRef:
    kind: str
    stable_id: str
    version: str
    content_hash: str
    status: str
    data_domain_id: str
    semantic_schema_version: str
    display_name: str | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    compatibility_metadata: dict[str, Any] = field(default_factory=dict)

    def catalog_ref(self) -> CatalogRef:
        return CatalogRef(kind=self.kind, stable_id=self.stable_id, version=self.version)  # type: ignore[arg-type]

    def pin(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "stable_id": self.stable_id,
            "version": self.version,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class CatalogValidationContext:
    tenant_id: str
    data_domain_id: str
    location: dict[str, Any]
    expected_input_schema: dict[str, Any] | None = None
    expected_output_schema: dict[str, Any] | None = None
    source_entity_type_ref: CatalogRef | None = None
    target_entity_type_ref: CatalogRef | None = None


@dataclass(frozen=True)
class CatalogValidationResult:
    resolved: tuple[ResolvedCatalogRef, ...]
    errors: tuple[CatalogResolutionError, ...] = ()


class CatalogResolver(Protocol):
    async def resolve(
        self,
        tenant_id: str,
        ref: CatalogRef,
        expected_kind: str,
        *,
        at_version: str | None = None,
        context: CatalogValidationContext | None = None,
    ) -> ResolvedCatalogRef: ...

    async def validate(
        self,
        tenant_id: str,
        refs: list[tuple[CatalogRef, str]],
        context: CatalogValidationContext,
    ) -> CatalogValidationResult: ...


class UnavailableCatalogResolver:
    """Production-safe default until a signed authoritative catalog exists."""

    async def resolve(
        self,
        tenant_id: str,
        ref: CatalogRef,
        expected_kind: str,
        *,
        at_version: str | None = None,
        context: CatalogValidationContext | None = None,
    ) -> ResolvedCatalogRef:
        del tenant_id, expected_kind, at_version, context
        raise CatalogResolutionError("CATALOG_REF_NOT_FOUND", ref, "No authoritative CatalogResolver is configured.")

    async def validate(
        self,
        tenant_id: str,
        refs: list[tuple[CatalogRef, str]],
        context: CatalogValidationContext,
    ) -> CatalogValidationResult:
        errors: list[CatalogResolutionError] = []
        for ref, expected_kind in refs:
            try:
                await self.resolve(tenant_id, ref, expected_kind, context=context)
            except CatalogResolutionError as error:
                errors.append(error)
        return CatalogValidationResult((), tuple(errors))


class FakeCatalogResolver:
    """Contract-test adapter; never registered by the production root."""

    test_only = True

    def __init__(self, entries: list[ResolvedCatalogRef] | None = None) -> None:
        self._entries = {(entry.kind, entry.stable_id, entry.version): entry for entry in entries or []}

    def add(self, entry: ResolvedCatalogRef) -> None:
        self._entries[(entry.kind, entry.stable_id, entry.version)] = entry

    async def resolve(
        self,
        tenant_id: str,
        ref: CatalogRef,
        expected_kind: str,
        *,
        at_version: str | None = None,
        context: CatalogValidationContext | None = None,
    ) -> ResolvedCatalogRef:
        del tenant_id
        if ref.kind != expected_kind:
            raise CatalogResolutionError("CATALOG_REF_KIND_MISMATCH", ref, "CatalogRef kind does not match its use.")
        if at_version is not None and at_version != ref.version:
            raise CatalogResolutionError("CATALOG_REF_NOT_FOUND", ref, "CatalogRef version is not exact.")
        entry = self._entries.get((ref.kind, ref.stable_id, ref.version))
        if entry is None:
            raise CatalogResolutionError("CATALOG_REF_NOT_FOUND", ref, "CatalogRef does not exist.")
        if entry.status != "active":
            raise CatalogResolutionError("CATALOG_REF_INACTIVE", ref, "CatalogRef is not active.")
        if context is not None and entry.data_domain_id not in {context.data_domain_id, "global"}:
            raise CatalogResolutionError(
                "CATALOG_REF_DOMAIN_FORBIDDEN", ref, "CatalogRef is outside the allowed data domain."
            )
        return entry

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
