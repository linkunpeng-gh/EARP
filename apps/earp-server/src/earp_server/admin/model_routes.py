"""Model config routes (PRD-2026-031)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from earp_server.admin import model_service
from earp_server.infra import model_registry

router = APIRouter(prefix="/api", tags=["models"])


async def _require_admin(req: Request) -> None:
    """管理端门禁（2026-08-18 越权修复）：仅 is_admin 角色可变更模型配置。"""
    from earp_server.policy.roles_service import is_admin_role

    if not await is_admin_role(req.app.state.engine, req.state.tenant_id, req.state.role_id):
        raise HTTPException(status_code=403, detail="仅 Admin 角色可执行此操作")


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
    copilot: str | None = None  # Copilot 配置助手专用模型
    # Chatflow QU 升级 prompt 模板（可选；空串=清除）；需已配置默认 LLM
    qu_prompt_template: str | None = None


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
    await _require_admin(req)
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
    await _require_admin(req)
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
    await _require_admin(req)
    deleted, error = await model_service.delete_model_config(req.app.state.engine, req.state.tenant_id, config_id)
    if error:
        raise HTTPException(status_code=409, detail=error)
    if not deleted:
        raise HTTPException(status_code=404, detail="Model config not found")


@router.post("/model-configs/{config_id}/test")
async def test_model_config(config_id: str, req: Request) -> dict:
    await _require_admin(req)
    return await model_service.test_connection(req.app.state.engine, req.state.tenant_id, config_id)


@router.get("/system-model-settings")
async def get_system_settings(req: Request) -> dict:
    out = await model_service.get_system_model_settings(req.app.state.engine, req.state.tenant_id)
    out["qu_prompt_template"] = await model_service.get_qu_prompt_template(req.app.state.engine, req.state.tenant_id)
    # 内置默认模板文本（前端「载入默认」以此为准，占位符与租户模板一致）
    from earp_server.ontology.understanding import DEFAULT_UPGRADE_PROMPT_TEMPLATE

    out["default_qu_prompt"] = DEFAULT_UPGRADE_PROMPT_TEMPLATE
    return out


@router.put("/system-model-settings")
async def set_system_settings(req_body: SystemSettingsIn, req: Request) -> dict:
    await _require_admin(req)
    mapping = {k: v for k, v in req_body.model_dump().items() if k != "qu_prompt_template" and v}
    try:
        await model_service.set_system_model_settings(req.app.state.engine, req.state.tenant_id, mapping)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if req_body.qu_prompt_template is not None:
        try:
            await model_service.set_qu_prompt_template(
                req.app.state.engine, req.state.tenant_id, req_body.qu_prompt_template
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
    return await get_system_settings(req)
