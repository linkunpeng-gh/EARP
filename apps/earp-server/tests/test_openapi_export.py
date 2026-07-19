"""AC-08: openapi export is byte-stable and matches the committed baseline."""

from __future__ import annotations

import pathlib

import yaml

from earp_server.export_openapi import export_openapi

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = ROOT / "openapi.yaml"


def test_export_matches_committed_baseline() -> None:
    assert BASELINE.exists(), "openapi.yaml baseline missing - run `make openapi`"
    assert export_openapi() == BASELINE.read_text()


def test_export_is_deterministic() -> None:
    assert export_openapi() == export_openapi()


def test_sessions_schema_locks_runtime_py_contract() -> None:
    spec = yaml.safe_load(export_openapi())
    request = spec["components"]["schemas"]["SessionCreateRequest"]
    assert set(request["required"]) == {"user_id", "tenant_id", "role_id"}
    response = spec["components"]["schemas"]["SessionResponse"]
    assert {"session_id", "tenant_id", "user_id", "status"} <= set(response["properties"])
    assert "/v1/sessions" in spec["paths"]
