"""Catalog registration uses only independently verified authoritative pins."""

from __future__ import annotations

import pytest

from earp_server.catalog.hashing import content_hash
from earp_server.catalog.registration import CatalogRegistrationError, verified_source_ref
from earp_server.catalog.source import SourceObject


class Adapter:
    def __init__(self, source: SourceObject) -> None:
        self.source = source

    async def fetch_exact(self, kind: str, stable_id: str, version: str) -> SourceObject:
        return self.source

    async def list_since(self, cursor: str | None) -> tuple[list[SourceObject], str | None]:
        return [], cursor


def _source(*, declared_hash: str | None = None, schema: str = "catalog-unit/v1") -> SourceObject:
    payload = {
        "kind": "unit",
        "stable_id": "common.mass.tonne",
        "version": "1.0.0",
        "unit_id": "common.mass.tonne",
    }
    return SourceObject(
        kind="unit",
        stable_id="common.mass.tonne",
        version="1.0.0",
        canonical_input=payload,
        content_hash=declared_hash or content_hash(payload, schema_version=schema),
        schema_version=schema,
        status="active",
        data_domain_id="production",
    )


@pytest.mark.asyncio
async def test_registration_accepts_only_matching_authoritative_hash() -> None:
    source = _source()
    result = await verified_source_ref(
        Adapter(source),
        kind="unit",
        stable_id=source.stable_id,
        version=source.version,
    )
    assert result == source

    with pytest.raises(CatalogRegistrationError, match="hash mismatch"):
        await verified_source_ref(
            Adapter(_source(declared_hash="0" * 64)),
            kind="unit",
            stable_id=source.stable_id,
            version=source.version,
        )


@pytest.mark.asyncio
async def test_registration_unknown_schema_version_fails_closed() -> None:
    source = _source(declared_hash="a" * 64, schema="catalog-unit/v2")
    with pytest.raises(CatalogRegistrationError, match="unsupported"):
        await verified_source_ref(
            Adapter(source),
            kind="unit",
            stable_id=source.stable_id,
            version=source.version,
        )
