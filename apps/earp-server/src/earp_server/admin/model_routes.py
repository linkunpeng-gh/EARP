"""Model config routes (PRD-2026-031)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from earp_server.admin import model_service
from earp_server.infra import model_registry

router = APIRouter(prefix="/api", tags=["models"])


class ModelConfigIn(BaseModel):
    provider: str
    model_type: str
    model_name: str
    credentials: dict = {}


class ModelConfigUpdate(BaseModel):
    credentials: dict | None = None
    enabled: bool | None = None
    is_default: bool | None = None


class SystemSettingsIn(BaseModel):
    llm: str | None = None
    embedding: str | None = None
    rerank: str | None = None


@router.get("/model-providers")
async def list_providers(req: Request) -> list[dict]:
    """Provider catalog + per-provider configured models."""
    providers = model_registry.list_providers()
    configs = await model_service.list_model_configs(req.app.state.engine, req.state.tenant_id)
    by_provider: dict[str, list[dict]] = {}
    for c in configs:
        by_provider.setdefault(c["provider"], []).append(c)
    for p in providers:
        p["configured_models"] = by_provider.get(p["provider"], [])
    return providers


@router.post("/model-configs", status_code=201)
async def create_model_config(req_body: ModelConfigIn, req: Request) -> dict:
    try:
        return await model_service.create_model_config(
            req.app.state.engine,
            req.state.tenant_id,
            req_body.provider,
            req_body.model_type,
            req_body.model_name,
            req_body.credentials,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.get("/model-configs")
async def list_model_configs(req: Request, model_type: str | None = None) -> list[dict]:
    return await model_service.list_model_configs(req.app.state.engine, req.state.tenant_id, model_type)


@router.put("/model-configs/{config_id}")
async def update_model_config(config_id: str, req_body: ModelConfigUpdate, req: Request) -> dict:
    updated = await model_service.update_model_config(
        req.app.state.engine,
        req.state.tenant_id,
        config_id,
        credentials=req_body.credentials,
        enabled=req_body.enabled,
        is_default=req_body.is_default,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Model config not found")
    return updated


@router.delete("/model-configs/{config_id}", status_code=204)
async def delete_model_config(config_id: str, req: Request) -> None:
    deleted, error = await model_service.delete_model_config(req.app.state.engine, req.state.tenant_id, config_id)
    if error:
        raise HTTPException(status_code=409, detail=error)
    if not deleted:
        raise HTTPException(status_code=404, detail="Model config not found")


@router.post("/model-configs/{config_id}/test")
async def test_model_config(config_id: str, req: Request) -> dict:
    return await model_service.test_connection(req.app.state.engine, req.state.tenant_id, config_id)


@router.get("/system-model-settings")
async def get_system_settings(req: Request) -> dict:
    return await model_service.get_system_model_settings(req.app.state.engine, req.state.tenant_id)


@router.put("/system-model-settings")
async def set_system_settings(req_body: SystemSettingsIn, req: Request) -> dict:
    mapping = {k: v for k, v in req_body.model_dump().items() if v}
    try:
        return await model_service.set_system_model_settings(req.app.state.engine, req.state.tenant_id, mapping)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
