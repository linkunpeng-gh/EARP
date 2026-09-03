"""Catalog Phase 1 frozen hash contract tests."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from earp_server.catalog.hashing import (
    CatalogCanonicalizationError,
    canonical_json,
    content_hash,
)

ROOT = Path(__file__).resolve().parents[3]


def test_production_hashes_match_all_frozen_golden_vectors() -> None:
    fixtures = json.loads((ROOT / "arch/catalog/schemas/golden-hashes.json").read_text())
    for fixture in fixtures.values():
        payload = json.loads(fixture["canonical_json"], parse_float=Decimal)
        assert canonical_json(payload, schema_version=fixture["schema_version"]) == fixture["canonical_json"]
        assert content_hash(payload, schema_version=fixture["schema_version"]) == fixture["content_hash"]


def test_schema_version_is_required_and_unknown_versions_fail_closed() -> None:
    with pytest.raises(CatalogCanonicalizationError, match="unknown"):
        content_hash({"kind": "unit"}, schema_version="catalog-unit/v2")


def test_semantic_collection_duplicates_and_binary_floats_are_rejected() -> None:
    with pytest.raises(CatalogCanonicalizationError, match="duplicate"):
        canonical_json(
            {
                "entries": [
                    {"kind": "unit", "stable_id": "u", "version": "1"},
                    {"kind": "unit", "stable_id": "u", "version": "1"},
                ]
            },
            schema_version="catalog-manifest/v1",
        )
    with pytest.raises(CatalogCanonicalizationError, match="binary floats"):
        canonical_json({"value": 1.5}, schema_version="catalog-unit/v1")
