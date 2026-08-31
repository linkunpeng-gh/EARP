"""OpenAPI guardrails for the frozen N01A transport contract."""

from fastapi import FastAPI

from earp_server.causal_model_management.routes import router


def _spec() -> dict:
    app = FastAPI()
    app.include_router(router)
    return app.openapi()


def test_n01a_paths_and_shared_error_responses_are_exported() -> None:
    spec = _spec()
    paths = spec["paths"]
    required = {
        "/v1/ecmc/causal-models",
        "/v1/ecmc/causal-models/{model_id}/versions",
        "/v1/ecmc/causal-models/{model_id}/versions/{version_id}/validate",
        "/v1/ecmc/causal-models/{model_id}/versions/{version_id}/publish",
        "/v1/ecmc/causal-models/{model_id}/activate",
        "/v1/ecmc/catalog-change-requests/{request_id}/retry-fulfillment",
    }
    assert required <= paths.keys()
    for path_item in paths.values():
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            assert {"403", "404", "409", "422"} <= operation["responses"].keys()


def test_n01a_write_operations_export_idempotency_and_version_if_match_headers() -> None:
    spec = _spec()
    version_mutations = {
        ("patch", "/v1/ecmc/causal-models/{model_id}/versions/{version_id}"),
        ("put", "/v1/ecmc/causal-models/{model_id}/versions/{version_id}/nodes/{node_key}"),
        ("post", "/v1/ecmc/causal-models/{model_id}/versions/{version_id}/publish"),
        ("post", "/v1/ecmc/causal-models/{model_id}/activate"),
    }
    for method, path in version_mutations:
        operation = spec["paths"][path][method]
        parameters = {parameter["name"] for parameter in operation.get("parameters", [])}
        assert "Idempotency-Key" in parameters
        assert "If-Match" in parameters

    validate_operation = spec["paths"][
        "/v1/ecmc/causal-models/{model_id}/versions/{version_id}/validate"
    ]["post"]
    validate_parameters = {p["name"] for p in validate_operation["parameters"]}
    assert {"Idempotency-Key"} <= validate_parameters
    assert "If-Match" not in validate_parameters

    compile_operation = spec["paths"][
        "/v1/ecmc/causal-models/{model_id}/versions/{version_id}/compile"
    ]["post"]
    assert "Idempotency-Key" in {p["name"] for p in compile_operation["parameters"]}
    assert "If-Match" not in {p["name"] for p in compile_operation["parameters"]}


def test_n01a_schema_components_are_strictly_present() -> None:
    schemas = _spec()["components"]["schemas"]
    for name in ("CatalogRef", "ValidationIssue", "ValidationResult", "ErrorResponse", "ActivateRequest"):
        assert name in schemas
    assert schemas["CatalogRef"]["additionalProperties"] is False
