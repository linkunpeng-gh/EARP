"""Roles 管理路由（tech-debt #9：roles 页开放配置 + Admin 全权限通用机制）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from earp_server.policy import roles_service

router = APIRouter(prefix="/api", tags=["roles"])


class RoleIn(BaseModel):
    name: str
    role_id: str | None = None  # 可选（缺省自动生成 r-xxxx）
    permissions: list[str] = []
    data_scope: str = "self"
    data_domain_access: list[dict] = []
    is_admin: bool = False


class RoleUpdate(BaseModel):
    name: str | None = None
    permissions: list[str] | None = None
    data_scope: str | None = None
    data_domain_access: list[dict] | None = None
    is_admin: bool | None = None


@router.get("/roles")
async def list_roles(req: Request) -> list[dict]:
    return await roles_service.list_roles(req.app.state.engine, req.state.tenant_id)


@router.get("/roles/{role_id}")
async def get_role(role_id: str, req: Request) -> dict:
    role = await roles_service.get_role(req.app.state.engine, req.state.tenant_id, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail=f"Role not found: {role_id}")
    return role


@router.post("/roles", status_code=201)
async def create_role(req_body: RoleIn, req: Request) -> dict:
    try:
        return await roles_service.create_role(
            req.app.state.engine,
            req.state.tenant_id,
            name=req_body.name,
            role_id=req_body.role_id,
            permissions=req_body.permissions,
            data_scope=req_body.data_scope,
            data_domain_access=req_body.data_domain_access,
            is_admin=req_body.is_admin,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.put("/roles/{role_id}")
async def update_role(role_id: str, req_body: RoleUpdate, req: Request) -> dict:
    try:
        role = await roles_service.update_role(
            req.app.state.engine,
            req.state.tenant_id,
            role_id,
            name=req_body.name,
            permissions=req_body.permissions,
            data_scope=req_body.data_scope,
            data_domain_access=req_body.data_domain_access,
            is_admin=req_body.is_admin,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if role is None:
        raise HTTPException(status_code=404, detail=f"Role not found: {role_id}")
    return role


@router.delete("/roles/{role_id}")
async def delete_role(role_id: str, req: Request) -> dict:
    try:
        deleted = await roles_service.delete_role(req.app.state.engine, req.state.tenant_id, role_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Role not found: {role_id}")
    return {"role_id": role_id, "deleted": True}
