"""Resolver contract vectors: exact pin, tenant/domain and drift fail-closed."""

from __future__ import annotations

from copy import deepcopy

import pytest

from earp_server.catalog.domain import envelope_hash, manifest_content_hash, pack_content_hash
from earp_server.catalog.resolver import ManifestCatalogResolver
from earp_server.causal_model_management.catalog import CatalogResolutionError, CatalogValidationContext
from earp_server.causal_model_management.schemas import CatalogRef


def _active() -> tuple[dict, dict]:
    entry = {
        "kind": "metric",
        "stable_id": "coal.output",
        "version": "1.0.0",
        "content_hash": "a" * 64,
        "status": "active",
        "data_domain_id": "production",
        "semantic_schema_version": "catalog-metric/v1",
    }
    pack = {"pack_id": "platform-base", "layer": "platform", "version": "1.0.0", "entries": [entry]}
    pack["content_hash"] = pack_content_hash(pack["pack_id"], pack["layer"], pack["version"], pack["entries"])
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
        "pack_lock": [{key: pack[key] for key in ("pack_id", "layer", "version", "content_hash")}],
        "entries": [entry],
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
    return manifest, attestation


@pytest.mark.asyncio
async def test_resolver_blocks_absent_cross_domain_and_hash_drift() -> None:
    manifest, attestation = _active()
    source_hash = {"value": "a" * 64}
    resolver = ManifestCatalogResolver(
        lambda tenant: (1, manifest, attestation) if tenant == "jqmk" else None,
        lambda _tenant, _entry: source_hash["value"],
    )
    ref = CatalogRef(kind="metric", stable_id="coal.output", version="1.0.0")
    context = CatalogValidationContext("jqmk", "production", {})
    assert (await resolver.resolve("jqmk", ref, "metric", context=context)).content_hash == "a" * 64

    with pytest.raises(CatalogResolutionError, match="outside") as forbidden:
        await resolver.resolve("jqmk", ref, "metric", context=CatalogValidationContext("jqmk", "safety", {}))
    assert forbidden.value.code == "CATALOG_REF_DOMAIN_FORBIDDEN"

    source_hash["value"] = "b" * 64
    with pytest.raises(CatalogResolutionError, match="drifted") as cached_drift:
        await resolver.resolve("jqmk", ref, "metric", context=context)
    assert cached_drift.value.code == "CATALOG_REF_NOT_FOUND"

    drifted = deepcopy(manifest)
    drift_resolver = ManifestCatalogResolver(
        lambda _tenant: (2, drifted, attestation), lambda _tenant, _entry: source_hash["value"]
    )
    with pytest.raises(CatalogResolutionError, match="drifted"):
        await drift_resolver.resolve("jqmk", ref, "metric", context=context)
