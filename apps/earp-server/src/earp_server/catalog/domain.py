"""Pure Catalog Pack and Manifest composition rules (Phase 1)."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from .hashing import content_hash

PACK_HASH_SCHEMA = "catalog-pack/v1"
MANIFEST_HASH_SCHEMA = "catalog-manifest/v1"
ATTESTATION_HASH_SCHEMA = "catalog-attestation/v1"
PACK_LAYERS = ("platform", "industry", "enterprise")
MANIFEST_HASH_FIELDS = (
    "manifest_schema_version",
    "manifest_id",
    "manifest_revision",
    "scope",
    "pack_lock",
    "entries",
    "owners",
    "resolver_adapter",
)
ENVELOPE_HASH_FIELDS = (
    "manifest_hash",
    "signoff_tag",
    "change_order",
    "signed_at",
    "effective_from",
    "effective_until",
    "signers",
)


class CatalogCompositionError(ValueError):
    """A Pack or Manifest violates an immutable Phase 1 composition rule."""


def _identity(entry: dict[str, Any]) -> tuple[str, str, str]:
    try:
        return str(entry["kind"]), str(entry["stable_id"]), str(entry["version"])
    except KeyError as error:
        raise CatalogCompositionError(f"entry misses exact-ref field: {error.args[0]}") from error


def _ordered(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted((deepcopy(entry) for entry in entries), key=_identity)


def pack_content_hash(pack_id: str, layer: str, version: str, entries: Iterable[dict[str, Any]]) -> str:
    """Hash only immutable Pack identity and exact-reference pins."""
    if layer not in PACK_LAYERS:
        raise CatalogCompositionError(f"unsupported pack layer: {layer}")
    pins = []
    for entry in _ordered(entries):
        if not isinstance(entry.get("content_hash"), str):
            raise CatalogCompositionError(f"entry {_identity(entry)} misses content_hash")
        pins.append({key: entry[key] for key in ("kind", "stable_id", "version", "content_hash")})
    return content_hash(
        {"pack_id": pack_id, "layer": layer, "version": version, "entries": pins},
        schema_version=PACK_HASH_SCHEMA,
    )


def compose_packs(packs: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compose layers with exact dedupe; same identity + different pin fails closed."""
    selected = list(packs)
    layers = [pack.get("layer") for pack in selected]
    if len(layers) != len(set(layers)) or any(layer not in PACK_LAYERS for layer in layers):
        raise CatalogCompositionError("a manifest may contain at most one Pack per supported layer")

    effective: dict[tuple[str, str, str], dict[str, Any]] = {}
    pack_lock: list[dict[str, Any]] = []
    for pack in selected:
        try:
            declared_hash = str(pack["content_hash"])
            computed_hash = pack_content_hash(pack["pack_id"], pack["layer"], pack["version"], pack["entries"])
        except KeyError as error:
            raise CatalogCompositionError(f"pack misses required field: {error.args[0]}") from error
        if declared_hash != computed_hash:
            raise CatalogCompositionError(f"pack hash mismatch: {pack['pack_id']}@{pack['version']}")
        pack_lock.append({key: pack[key] for key in ("pack_id", "layer", "version", "content_hash")})
        for entry in pack["entries"]:
            key = _identity(entry)
            previous = effective.get(key)
            if previous is not None and previous.get("content_hash") != entry.get("content_hash"):
                raise CatalogCompositionError(f"conflicting exact ref across Packs: {key}")
            if previous is None:
                copy = deepcopy(entry)
                copy.setdefault("source_pack_id", pack["pack_id"])
                effective[key] = copy
    return _ordered(effective.values()), sorted(pack_lock, key=lambda item: (item["layer"], item["pack_id"]))


def manifest_content_hash(manifest: dict[str, Any]) -> str:
    """Compute the frozen Manifest content projection hash."""
    return content_hash(
        {field: deepcopy(manifest[field]) for field in MANIFEST_HASH_FIELDS},
        schema_version=MANIFEST_HASH_SCHEMA,
    )


def envelope_hash(attestation: dict[str, Any]) -> str:
    """Bind the signed Manifest hash to signers and its effective window."""
    return content_hash(
        {field: deepcopy(attestation.get(field)) for field in ENVELOPE_HASH_FIELDS},
        schema_version=ATTESTATION_HASH_SCHEMA,
    )


def validate_manifest_for_activation(manifest: dict[str, Any], attestation: dict[str, Any]) -> None:
    """Fail closed unless both the immutable content and signed envelope verify."""
    if manifest.get("manifest_hash") != manifest_content_hash(manifest):
        raise CatalogCompositionError("manifest hash mismatch")
    if attestation.get("manifest_hash") != manifest["manifest_hash"]:
        raise CatalogCompositionError("attestation does not bind manifest hash")
    if attestation.get("envelope_hash") != envelope_hash(attestation):
        raise CatalogCompositionError("attestation envelope hash mismatch")
    if manifest.get("resolver_adapter", {}).get("identity") != "earp.catalog.resolver.api/v1":
        raise CatalogCompositionError("resolver adapter identity mismatch")
    if any(entry.get("status") == "suspected_missing" for entry in manifest.get("entries", [])):
        raise CatalogCompositionError("suspected_missing entries cannot enter a new manifest")
