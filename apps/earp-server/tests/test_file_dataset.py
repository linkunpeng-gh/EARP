from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from earp_server.capability.resolution import FileDatasetCapabilityResolver
from earp_server.file_dataset import (
    FileDatasetError,
    acquire_observation,
    parse_manifest,
    validate_package,
)


def _manifest() -> dict:
    return {
        "schema_version": "earp-file-dataset/v1",
        "dataset": {"id": "mine-demo", "name": "Mine demo"},
        "providers": [
            {
                "provider_key": "file-production-v1",
                "capability_contract_ref": "production_metric_query",
                "file": "production.csv",
                "entity_column": "entity_id",
                "time_column": "observed_at",
                "requirements": {
                    "production_actual_and_baseline": {
                        "value_column": "value",
                        "baseline_column": "baseline",
                        "unit": "t",
                    }
                },
            }
        ],
    }


def test_manifest_rejects_path_traversal() -> None:
    manifest = _manifest()
    manifest["providers"][0]["file"] = "../production.csv"
    with pytest.raises(FileDatasetError, match="unsafe"):
        parse_manifest(json.dumps(manifest).encode())


def test_optional_catalog_sections_are_structurally_validated() -> None:
    cases = [
        ({"data_domains": [{"name": "No id"}]}, "data_domain_id"),
        ({"entity_types": [{"entity_type_id": "fd-mine", "kind": "weird"}]}, "unsupported kind"),
        (
            {"relation_types": [{"relation_type_id": "fd-owns", "cardinality": "many:few"}]},
            "unsupported cardinality",
        ),
        (
            {"data_domains": [{"data_domain_id": "fd-prod", "data_classification": "secret"}]},
            "unsupported data_classification",
        ),
        ({"entity_types": "not-a-list"}, "must be a list of objects"),
        ({"relation_types": ["not-an-object"]}, "must be a list of objects"),
        ({"data_domains": [{"data_domain_id": "x" * 65}]}, "at most 64 characters"),
    ]
    for section, expected in cases:
        manifest = _manifest()
        manifest.update(section)
        with pytest.raises(FileDatasetError, match=expected):
            parse_manifest(json.dumps(manifest).encode())


def test_optional_catalog_sections_accept_valid_entries() -> None:
    manifest = _manifest()
    manifest["data_domains"] = [
        {"data_domain_id": "fd-production", "name": "Production", "data_classification": "restricted"}
    ]
    manifest["entity_types"] = [
        {"entity_type_id": "fd-mine", "name": "Mine", "kind": "concept", "data_domain_id": "fd-production"}
    ]
    manifest["relation_types"] = [
        {
            "relation_type_id": "fd-owns",
            "name": "Owns",
            "source_type": "fd-mine",
            "target_type": "fd-mine",
            "cardinality": "1:N",
        }
    ]
    parsed = parse_manifest(json.dumps(manifest).encode())
    assert parsed["relation_types"][0]["cardinality"] == "1:N"
    assert parsed["data_domains"][0]["data_classification"] == "restricted"


def test_optional_catalog_sections_may_be_absent() -> None:
    parsed = parse_manifest(json.dumps(_manifest()).encode())
    assert parsed["dataset"]["id"] == "mine-demo"


def test_validation_skips_bad_rows_with_warnings() -> None:
    manifest = parse_manifest(json.dumps(_manifest()).encode())
    report = validate_package(
        manifest,
        {
            "production.csv": (
                b"entity_id,observed_at,value,baseline\n"
                b"mine-3,2026-08-28T01:00:00+08:00,10,12\n"
                b"mine-3,not-a-time,bad,12\n"
            )
        },
    )
    assert report["usable_provider_rows"] == 1
    assert report["warning_count"] == 1
    assert report["warnings"][0]["row"] == 3


def test_file_resolver_matches_contract_and_requirement() -> None:
    resolver = FileDatasetCapabilityResolver(_manifest())
    result = resolver.resolve(
        {
            "capability_contract_ref": "production_metric_query",
            "requirement_key": "production_actual_and_baseline",
            "requirement_level": "required",
        }
    )
    assert result.provider_key == "file-production-v1"
    assert result.status == "bound"


@pytest.mark.asyncio
async def test_file_provider_filters_half_open_window_and_aggregates_sum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = (
        b"entity_id,observed_at,value,baseline\n"
        b"mine-3,2026-08-28T00:00:00+08:00,10,12\n"
        b"mine-3,2026-08-28T12:00:00+08:00,20,22\n"
        b"mine-3,2026-08-29T00:00:00+08:00,99,99\n"
        b"mine-4,2026-08-28T12:00:00+08:00,88,88\n"
    )
    base = tmp_path / "tenant-demo" / "mine-demo" / ("a" * 64)
    base.mkdir(parents=True)
    (base / "production.csv").write_bytes(content)

    async def snapshot(*_args, **_kwargs):
        return {
            "dataset_id": "mine-demo",
            "content_hash": "a" * 64,
            "manifest": _manifest(),
            "files": [
                {
                    "name": "production.csv",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                }
            ],
            "storage_relpath": str(Path("tenant-demo") / "mine-demo" / ("a" * 64)),
        }

    monkeypatch.setattr("earp_server.file_dataset.published_snapshot", snapshot)
    result = await acquire_observation(
        object(),  # type: ignore[arg-type]
        "tenant-demo",
        tmp_path,
        {
            "prepare_id": "prepare-1",
            "requirement_id": "req-1",
            "source_requirement_id": "source-1",
            "requirement_key": "production_actual_and_baseline",
            "node_key": "production_output",
            "requirement_level": "required",
            "capability_contract_ref": "production_metric_query",
            "provider_key": "file-production-v1",
            "target": {"entity_id": "mine-3", "entity_type": "mine"},
            "time_window": {
                "start": "2026-08-28T00:00:00+08:00",
                "end": "2026-08-29T00:00:00+08:00",
            },
            "measurement": {"aggregation": "sum_over_production_day", "unit": "t"},
            "file_dataset": {"dataset_id": "mine-demo", "content_hash": "a" * 64},
        },
    )
    observation = result["observation"]
    assert observation["value"] == 30
    assert observation["baseline_value"] == 34
    assert observation["quality"]["matched_rows"] == 2
    assert observation["provenance"]["dataset_content_hash"] == "a" * 64
