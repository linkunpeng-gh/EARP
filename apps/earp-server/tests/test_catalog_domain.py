"""Phase 1 Pack and Manifest fail-closed contract vectors."""

from __future__ import annotations

from copy import deepcopy

import pytest

from earp_server.catalog.domain import (
    CatalogCompositionError,
    compose_packs,
    envelope_hash,
    manifest_content_hash,
    pack_content_hash,
    validate_manifest_for_activation,
)


def _pack(layer: str, pack_id: str, entries: list[dict]) -> dict:
    pack = {"pack_id": pack_id, "layer": layer, "version": "1.0.0", "entries": entries}
    pack["content_hash"] = pack_content_hash(pack_id, layer, pack["version"], entries)
    return pack


def _entry(content_hash: str = "a" * 64, stable_id: str = "common.unit") -> dict:
    return {
        "kind": "unit",
        "stable_id": stable_id,
        "version": "1.0.0",
        "content_hash": content_hash,
        "status": "active",
        "data_domain_id": "production",
        "semantic_schema_version": "catalog-unit/v1",
    }


def test_pack_composition_rejects_same_exact_ref_with_different_hash() -> None:
    with pytest.raises(CatalogCompositionError, match="conflicting"):
        compose_packs(
            [
                _pack("platform", "platform-base", [_entry("a" * 64)]),
                _pack("industry", "industry-base", [_entry("b" * 64)]),
            ]
        )


def test_pack_composition_deduplicates_only_identical_pins() -> None:
    entries, lock = compose_packs(
        [
            _pack("platform", "platform-base", [_entry()]),
            _pack("industry", "industry-base", [_entry(), _entry(stable_id="coal.unit")]),
        ]
    )
    assert [entry["stable_id"] for entry in entries] == ["coal.unit", "common.unit"]
    assert [(item["layer"], item["pack_id"]) for item in lock] == [
        ("industry", "industry-base"),
        ("platform", "platform-base"),
    ]


def test_activation_requires_manifest_and_envelope_hashes() -> None:
    entries, lock = compose_packs([_pack("platform", "platform-base", [_entry()])])
    manifest = {
        "manifest_schema_version": "catalog-manifest/v1",
        "manifest_id": "coal.sdrh.jqmk.production",
        "manifest_revision": 1,
        "scope": {
            "industry_scope": "coal",
            "enterprise_scope": "sdrh",
            "tenant_id": "jqmk",
            "data_domains": ["production"],
        },
        "pack_lock": lock,
        "entries": entries,
        "owners": [{"role_key": "owner", "name": "Owner", "team": "EARP"}],
        "resolver_adapter": {"identity": "earp.catalog.resolver.api/v1", "contract_version": "catalog-resolver/v1.0"},
    }
    manifest["manifest_hash"] = manifest_content_hash(manifest)
    attestation = {
        "manifest_hash": manifest["manifest_hash"],
        "signoff_tag": "tag",
        "change_order": "change",
        "signed_at": "2026-09-02T00:00:00+08:00",
        "effective_from": "2026-09-02T00:00:00+08:00",
        "effective_until": None,
        "signers": [{"role_key": "owner", "name": "Owner"}],
    }
    attestation["envelope_hash"] = envelope_hash(attestation)
    validate_manifest_for_activation(manifest, attestation)

    tampered = deepcopy(attestation)
    tampered["effective_from"] = "2026-10-02T00:00:00+08:00"
    with pytest.raises(CatalogCompositionError, match="envelope"):
        validate_manifest_for_activation(manifest, tampered)
