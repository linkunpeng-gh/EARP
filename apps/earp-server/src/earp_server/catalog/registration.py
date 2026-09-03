"""Authoritative-reference registration gate for Catalog Phase 1."""

from __future__ import annotations

from .hashing import CatalogCanonicalizationError, content_hash
from .source import SourceAdapter, SourceObject


class CatalogRegistrationError(ValueError):
    """The authoritative source cannot prove an immutable reference pin."""


async def verified_source_ref(adapter: SourceAdapter, *, kind: str, stable_id: str, version: str) -> SourceObject:
    """Fetch a source-owned object and independently verify its declared hash.

    No client-supplied hash enters this boundary.  Unknown schema versions and
    hash mismatches are rejected before any Catalog persistence can occur.
    """
    source = await adapter.fetch_exact(kind, stable_id, version)
    if (source.kind, source.stable_id, source.version) != (kind, stable_id, version):
        raise CatalogRegistrationError("source adapter returned an object different from the requested exact ref")
    try:
        recomputed = content_hash(source.canonical_input, schema_version=source.schema_version)
    except CatalogCanonicalizationError as error:
        raise CatalogRegistrationError("source object uses an unsupported canonicalization contract") from error
    if recomputed != source.content_hash:
        raise CatalogRegistrationError("authoritative content hash mismatch; registration blocked")
    return source
