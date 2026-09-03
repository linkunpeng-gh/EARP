"""The test-only source adapter exercises the same registration and pull gates."""

from __future__ import annotations

import pytest

from earp_server.catalog.hashing import content_hash
from earp_server.catalog.registration import CatalogRegistrationError, verified_source_ref
from earp_server.catalog.source import SourceObject
from earp_server.catalog.sync import _verify_source
from earp_server.catalog.testing import MockCatalogSourceAdapter


def _source(*, schema_version: str = "catalog-unit/v1", bad_hash: bool = False) -> SourceObject:
    payload = {
        "kind": "unit",
        "stable_id": "mock.mass.tonne",
        "version": "1.0.0",
        "unit_id": "mock.mass.tonne",
    }
    return SourceObject(
        kind="unit",
        stable_id="mock.mass.tonne",
        version="1.0.0",
        canonical_input=payload,
        content_hash="0" * 64 if bad_hash else content_hash(payload, schema_version=schema_version),
        schema_version=schema_version,
        status="active",
        data_domain_id="mock-domain",
    )


@pytest.mark.asyncio
async def test_mock_adapter_supports_exact_fetch_and_paging() -> None:
    source = _source()
    adapter = MockCatalogSourceAdapter("mock-unit", [source])
    assert await adapter.fetch_exact(source.kind, source.stable_id, source.version) == source
    page, cursor = await adapter.list_since(None)
    assert page == [source] and cursor == "1"
    assert await adapter.list_since(cursor) == ([], "1")
    assert adapter.source_identity(source) == "mock://mock-unit/unit/mock.mass.tonne/1.0.0"


@pytest.mark.asyncio
async def test_mock_adapter_still_uses_production_verification_gate() -> None:
    bad_hash = MockCatalogSourceAdapter("mock-unit", [_source(bad_hash=True)])
    with pytest.raises(CatalogRegistrationError, match="hash mismatch"):
        await verified_source_ref(
            bad_hash,
            kind="unit",
            stable_id="mock.mass.tonne",
            version="1.0.0",
        )

    unknown_schema = _source(schema_version="catalog-unit/v2", bad_hash=True)
    with pytest.raises(ValueError, match="unsupported"):
        _verify_source(MockCatalogSourceAdapter("mock-unit", [unknown_schema]), unknown_schema)
