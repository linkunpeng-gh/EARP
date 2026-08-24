"""应用中心治理：业务分类词表 + 应用使用权限矩阵（admin）。

设计：docs/superpowers/specs/2026-08-24-agent-center-design.md §4/§5.3。
- 门禁：is_admin_role（复用 roles_routes._require_admin 模式）。
- 分类词表 CRUD → conversation.category_service；权限矩阵 → policy.app_access_service。
- admin 域不在 import-linter 独立约束内，可自由组合各域 service。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from earp_server.admin.roles_routes import _require_admin
from earp_server.conversation import category_service
from earp_server.policy import app_access_service

router = APIRouter(
    prefix="/api",
    tags=["app_center"],
    dependencies=[Depends(_require_admin)],
)


class CategoryIn(BaseModel):
    name: str
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: str | None = None
    sort_order: int | None = None


class AppAccessIn(BaseModel):
    mode: str  # open | restricted
    roles: list[str] = []


# ── 分类词表 ────────────────────────────────────────────────────────────────
@router.get("/app_categories")
async def list_categories(req: Request) -> list[dict]:
    return await category_service.ensure_default_categories(req.app.state.engine, req.state.tenant_id)


@router.post("/app_categories", status_code=201)
async def create_category(req_body: CategoryIn, req: Request) -> dict:
    try:
        return await category_service.create_category(
            req.app.state.engine,
            req.state.tenant_id,
            req.state.user_id,
            req_body.name,
            sort_order=req_body.sort_order,
            bus=req.app.state.eventbus,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@router.patch("/app_categories/{category_id}")
async def update_category(category_id: str, req_body: CategoryUpdate, req: Request) -> dict:
    # 仅支持改名称（sort_order 不用于排序快照，本期保持简单；改名需同步 chat_apps）
    if req_body.name is None:
        raise HTTPException(status_code=422, detail="仅支持改名")
    try:
        cat = await category_service.rename_category(
            req.app.state.engine,
            req.state.tenant_id,
            req.state.user_id,
            category_id,
            req_body.name,
            bus=req.app.state.eventbus,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    if cat is None:
        raise HTTPException(status_code=404, detail=f"分类不存在: {category_id}")
    return cat


@router.delete("/app_categories/{category_id}")
async def delete_category(category_id: str, req: Request) -> dict:
    cat = await category_service.delete_category(
        req.app.state.engine,
        req.state.tenant_id,
        req.state.user_id,
        category_id,
        bus=req.app.state.eventbus,
    )
    if cat is None:
        raise HTTPException(status_code=404, detail=f"分类不存在: {category_id}")
    return cat


# ── 应用使用权限矩阵 ─────────────────────────────────────────────────────────
@router.get("/app_access")
async def get_app_access(req: Request, chat_app_id: str) -> dict:
    acc = await app_access_service.get_app_access(req.app.state.engine, req.state.tenant_id, chat_app_id)
    if acc is None:
        raise HTTPException(status_code=404, detail=f"应用不存在: {chat_app_id}")
    return acc


@router.put("/app_access/{chat_app_id}")
async def set_app_access(chat_app_id: str, req_body: AppAccessIn, req: Request) -> dict:
    try:
        return await app_access_service.set_app_access(
            req.app.state.engine,
            req.state.tenant_id,
            req.state.user_id,
            chat_app_id,
            mode=req_body.mode,
            roles=req_body.roles,
            bus=req.app.state.eventbus,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
