"""FastAPI transport adapter for the frozen N01A API contract."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, Response
from pydantic import BaseModel, ConfigDict

from .activation import ActivationCoordinator
from .compiler import CandidateCompileService
from .schemas import (
    ActivateRequest,
    CompileRequest,
    CreateCatalogChangeRequest,
    CreateModelRequest,
    CreateVersionRequest,
    PatchCatalogChangeRequest,
    PatchVersionRequest,
    PutEdgeRequest,
    PutEvidenceRequirementRequest,
    PutNodeRequest,
    PutRuleRequest,
    ReasonRequest,
    ValidateRequest,
    ValidationResult,
)
from .service import ActorContext, CausalModelService, etag, parse_if_match

router = APIRouter(prefix="/v1/ecmc", tags=["ecmc-causal-model-management"])

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
IfMatch = Annotated[str, Header(alias="If-Match")]


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    correlation_id: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    error: ErrorDetail


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {"model": ErrorResponse, "description": "Permission or data-domain access denied."},
    404: {"model": ErrorResponse, "description": "Resource is absent or not visible."},
    409: {"model": ErrorResponse, "description": "State, revision, idempotency, content or active CAS conflict."},
    422: {"model": ErrorResponse, "description": "Request schema or causal model validation failed."},
}


def _actor(request: Request) -> ActorContext:
    return ActorContext(
        tenant_id=request.state.tenant_id,
        actor_id=request.state.user_id,
        role_id=request.state.role_id,
        correlation_id=request.state.n01a_correlation_id,
    )


def _service(request: Request) -> CausalModelService:
    return CausalModelService(request.app.state.engine, request.app.state.n01a_catalog_resolver)


def _compiler(request: Request) -> CandidateCompileService:
    return CandidateCompileService(request.app.state.engine, request.app.state.n01a_catalog_resolver)


def _activation(request: Request) -> ActivationCoordinator:
    return ActivationCoordinator(request.app.state.engine, request.app.state.n01a_catalog_resolver)


def _write_response(response: Response, result: dict[str, Any], *, version: bool = False) -> dict[str, Any]:
    response.status_code = result["status_code"]
    body = result["body"]
    if version and isinstance(body.get("revision"), int):
        response.headers["ETag"] = etag(body["revision"])
    return body


@router.get("/causal-models", responses=ERROR_RESPONSES)
async def list_models(request: Request) -> list[dict[str, Any]]:
    return await _service(request).list_models(_actor(request))


@router.post("/causal-models", status_code=201, responses=ERROR_RESPONSES)
async def create_model(
    body: CreateModelRequest, request: Request, response: Response, idempotency_key: IdempotencyKey
) -> dict[str, Any]:
    return _write_response(
        response,
        await _service(request).create_model(_actor(request), body, idempotency_key),
        version=True,
    )


@router.get("/causal-models/{model_id}", responses=ERROR_RESPONSES)
async def get_model(model_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).get_model(_actor(request), model_id)


@router.get("/causal-models/{model_id}/versions", responses=ERROR_RESPONSES)
async def list_versions(model_id: str, request: Request) -> list[dict[str, Any]]:
    model = await _service(request).get_model(_actor(request), model_id)
    return model["versions"]


@router.post("/causal-models/{model_id}/versions", status_code=201, responses=ERROR_RESPONSES)
async def create_version(
    model_id: str,
    body: CreateVersionRequest,
    request: Request,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).create_version(
        _actor(request), model_id, body.clone_from_version_id, idempotency_key
    )
    return _write_response(response, result, version=True)


@router.get("/causal-models/{model_id}/versions/{version_id}", responses=ERROR_RESPONSES)
async def get_version(model_id: str, version_id: str, request: Request, response: Response) -> dict[str, Any]:
    body = await _service(request).get_version(_actor(request), model_id, version_id)
    response.headers["ETag"] = etag(body["revision"])
    return body


@router.patch("/causal-models/{model_id}/versions/{version_id}", responses=ERROR_RESPONSES)
async def patch_version(
    model_id: str,
    version_id: str,
    body: PatchVersionRequest,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).patch_version(
        _actor(request), model_id, version_id, body.applicability, parse_if_match(if_match), idempotency_key
    )
    return _write_response(response, result, version=True)


@router.put("/causal-models/{model_id}/versions/{version_id}/nodes/{node_key}", responses=ERROR_RESPONSES)
async def put_node(
    model_id: str,
    version_id: str,
    node_key: str,
    body: PutNodeRequest,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).put_node(
        _actor(request), model_id, version_id, node_key, body, parse_if_match(if_match), idempotency_key
    )
    return _write_response(response, result, version=True)


@router.delete("/causal-models/{model_id}/versions/{version_id}/nodes/{node_key}", responses=ERROR_RESPONSES)
async def delete_node(
    model_id: str,
    version_id: str,
    node_key: str,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).delete_draft_resource(
        _actor(request), model_id, version_id, "node", node_key, parse_if_match(if_match), idempotency_key
    )
    return _write_response(response, result, version=True)


@router.put("/causal-models/{model_id}/versions/{version_id}/edges/{edge_key}", responses=ERROR_RESPONSES)
async def put_edge(
    model_id: str,
    version_id: str,
    edge_key: str,
    body: PutEdgeRequest,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).put_edge(
        _actor(request), model_id, version_id, edge_key, body, parse_if_match(if_match), idempotency_key
    )
    return _write_response(response, result, version=True)


@router.delete("/causal-models/{model_id}/versions/{version_id}/edges/{edge_key}", responses=ERROR_RESPONSES)
async def delete_edge(
    model_id: str,
    version_id: str,
    edge_key: str,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).delete_draft_resource(
        _actor(request), model_id, version_id, "edge", edge_key, parse_if_match(if_match), idempotency_key
    )
    return _write_response(response, result, version=True)


@router.put("/causal-models/{model_id}/versions/{version_id}/rules/{rule_key}", responses=ERROR_RESPONSES)
async def put_rule(
    model_id: str,
    version_id: str,
    rule_key: str,
    body: PutRuleRequest,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).put_rule(
        _actor(request), model_id, version_id, rule_key, body, parse_if_match(if_match), idempotency_key
    )
    return _write_response(response, result, version=True)


@router.delete("/causal-models/{model_id}/versions/{version_id}/rules/{rule_key}", responses=ERROR_RESPONSES)
async def delete_rule(
    model_id: str,
    version_id: str,
    rule_key: str,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).delete_draft_resource(
        _actor(request), model_id, version_id, "rule", rule_key, parse_if_match(if_match), idempotency_key
    )
    return _write_response(response, result, version=True)


@router.put(
    "/causal-models/{model_id}/versions/{version_id}/evidence-requirements/{node_key}/{requirement_key}",
    responses=ERROR_RESPONSES,
)
async def put_evidence(
    model_id: str,
    version_id: str,
    node_key: str,
    requirement_key: str,
    body: PutEvidenceRequirementRequest,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).put_evidence(
        _actor(request),
        model_id,
        version_id,
        node_key,
        requirement_key,
        body,
        parse_if_match(if_match),
        idempotency_key,
    )
    return _write_response(response, result, version=True)


@router.delete(
    "/causal-models/{model_id}/versions/{version_id}/evidence-requirements/{node_key}/{requirement_key}",
    responses=ERROR_RESPONSES,
)
async def delete_evidence(
    model_id: str,
    version_id: str,
    node_key: str,
    requirement_key: str,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).delete_draft_resource(
        _actor(request),
        model_id,
        version_id,
        "evidence",
        requirement_key,
        parse_if_match(if_match),
        idempotency_key,
        node_key=node_key,
    )
    return _write_response(response, result, version=True)


@router.post(
    "/causal-models/{model_id}/versions/{version_id}/validate",
    response_model=ValidationResult,
    responses=ERROR_RESPONSES,
)
async def validate_model(
    model_id: str,
    version_id: str,
    body: ValidateRequest,
    request: Request,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    return _write_response(
        response,
        await _service(request).validate(_actor(request), model_id, version_id, body.mode, idempotency_key),
    )


@router.post("/causal-models/{model_id}/versions/{version_id}/submit-review", responses=ERROR_RESPONSES)
async def submit_review(
    model_id: str,
    version_id: str,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).submit_review(
        _actor(request), model_id, version_id, parse_if_match(if_match), idempotency_key
    )
    return _write_response(response, result, version=True)


@router.post("/causal-models/{model_id}/versions/{version_id}/reject", responses=ERROR_RESPONSES)
async def reject_review(
    model_id: str,
    version_id: str,
    body: ReasonRequest,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).reject_review(
        _actor(request), model_id, version_id, body.reason, parse_if_match(if_match), idempotency_key
    )
    return _write_response(response, result, version=True)


@router.post("/causal-models/{model_id}/versions/{version_id}/publish", responses=ERROR_RESPONSES)
async def publish(
    model_id: str,
    version_id: str,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _service(request).publish(
        _actor(request), model_id, version_id, parse_if_match(if_match), idempotency_key
    )
    return _write_response(response, result, version=True)


@router.post("/causal-models/{model_id}/versions/{version_id}/archive", responses=ERROR_RESPONSES)
async def archive(
    model_id: str,
    version_id: str,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _activation(request).archive(
        _actor(request), model_id, version_id, parse_if_match(if_match), idempotency_key
    )
    return _write_response(response, result, version=True)


@router.post("/causal-models/{model_id}/versions/{version_id}/compile", status_code=202, responses=ERROR_RESPONSES)
async def compile_model(
    model_id: str,
    version_id: str,
    body: CompileRequest,
    request: Request,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    return _write_response(
        response,
        await _compiler(request).request_compile(
            _actor(request), model_id, version_id, body.retry_of_compile_id, idempotency_key
        ),
    )


@router.post("/causal-models/{model_id}/activate", responses=ERROR_RESPONSES)
async def activate(
    model_id: str,
    body: ActivateRequest,
    request: Request,
    response: Response,
    if_match: IfMatch,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    result = await _activation(request).activate(
        _actor(request), model_id, body, parse_if_match(if_match), idempotency_key
    )
    return _write_response(response, result, version=True)


@router.get("/causal-models/{model_id}/versions/{version_id}/governance", responses=ERROR_RESPONSES)
async def governance(model_id: str, version_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).governance(_actor(request), model_id, version_id)


@router.get(
    "/causal-models/{model_id}/versions/{version_id}/compile-records/{compile_record_id}/artifact",
    responses=ERROR_RESPONSES,
)
async def artifact(model_id: str, version_id: str, compile_record_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).artifact(_actor(request), model_id, version_id, compile_record_id)


@router.get("/catalog-change-requests", responses=ERROR_RESPONSES)
async def list_catalog_requests(request: Request) -> list[dict[str, Any]]:
    return await _service(request).list_requests(_actor(request))


@router.post("/catalog-change-requests", status_code=201, responses=ERROR_RESPONSES)
async def create_catalog_request(
    body: CreateCatalogChangeRequest,
    request: Request,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    return _write_response(
        response, await _service(request).create_request(_actor(request), body, idempotency_key), version=True
    )


@router.get("/catalog-change-requests/{request_id}", responses=ERROR_RESPONSES)
async def get_catalog_request(request_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).get_request(_actor(request), request_id)


@router.patch("/catalog-change-requests/{request_id}", responses=ERROR_RESPONSES)
async def patch_catalog_request(
    request_id: str,
    body: PatchCatalogChangeRequest,
    request: Request,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    return _write_response(
        response,
        await _service(request).patch_request(_actor(request), request_id, body, idempotency_key),
        version=True,
    )


async def _catalog_command(
    request: Request, response: Response, request_id: str, command: str, key: str, reason: str | None = None
) -> dict[str, Any]:
    service = _service(request)
    commands = {
        "submit": lambda: service.submit_request(_actor(request), request_id, key),
        "approve": lambda: service.approve_request(_actor(request), request_id, key),
        "reject": lambda: service.reject_request(_actor(request), request_id, reason or "", key),
        "cancel": lambda: service.cancel_request(_actor(request), request_id, key),
        "retry-fulfillment": lambda: service.retry_fulfillment(_actor(request), request_id, key),
    }
    return _write_response(response, await commands[command](), version=True)


@router.post("/catalog-change-requests/{request_id}/submit", responses=ERROR_RESPONSES)
async def submit_catalog_request(
    request_id: str, request: Request, response: Response, idempotency_key: IdempotencyKey
) -> dict[str, Any]:
    return await _catalog_command(request, response, request_id, "submit", idempotency_key)


@router.post("/catalog-change-requests/{request_id}/approve", responses=ERROR_RESPONSES)
async def approve_catalog_request(
    request_id: str, request: Request, response: Response, idempotency_key: IdempotencyKey
) -> dict[str, Any]:
    return await _catalog_command(request, response, request_id, "approve", idempotency_key)


@router.post("/catalog-change-requests/{request_id}/reject", responses=ERROR_RESPONSES)
async def reject_catalog_request(
    request_id: str,
    body: ReasonRequest,
    request: Request,
    response: Response,
    idempotency_key: IdempotencyKey,
) -> dict[str, Any]:
    return await _catalog_command(request, response, request_id, "reject", idempotency_key, body.reason)


@router.post("/catalog-change-requests/{request_id}/cancel", responses=ERROR_RESPONSES)
async def cancel_catalog_request(
    request_id: str, request: Request, response: Response, idempotency_key: IdempotencyKey
) -> dict[str, Any]:
    return await _catalog_command(request, response, request_id, "cancel", idempotency_key)


@router.post("/catalog-change-requests/{request_id}/retry-fulfillment", responses=ERROR_RESPONSES)
async def retry_catalog_fulfillment(
    request_id: str, request: Request, response: Response, idempotency_key: IdempotencyKey
) -> dict[str, Any]:
    return await _catalog_command(request, response, request_id, "retry-fulfillment", idempotency_key)
