"""Evaluation API routes (B6) — eval set management + scoring runs.

prefix /v1/evaluations。跑分走后台任务（D4：asyncio.create_task，EventBus 先例）：
POST /runs 立即返回 run_id（status=running），GET /runs/{id} 轮询结果；
同集合并发 running → 409。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from earp_server.ontology import eval_service

router = APIRouter(prefix="/v1/evaluations", tags=["evaluations"])
logger = logging.getLogger(__name__)


class EvalSetIn(BaseModel):
    kind: str
    name: str = Field(min_length=1)
    description: str | None = None


class EvalCaseIn(BaseModel):
    query: str = Field(min_length=1)
    expected: dict[str, Any]
    note: str | None = None


class EvalCaseUpdate(BaseModel):
    query: str | None = None
    expected: dict[str, Any] | None = None
    note: str | None = None
    enabled: bool | None = None


def _to_http(exc: eval_service.EvalError) -> HTTPException:
    msg = str(exc)
    if "已有跑分进行中" in msg:
        return HTTPException(status_code=409, detail=msg)
    if "评估集不存在" in msg:
        return HTTPException(status_code=404, detail=msg)
    return HTTPException(status_code=400, detail=msg)


async def _ensure(req: Request) -> None:
    await eval_service.ensure_eval_sets(req.app.state.engine, req.state.tenant_id)


@router.get("/sets")
async def list_eval_sets(req: Request) -> dict[str, Any]:
    """评估集列表（+case_count + 最新跑分摘要）。"""
    await _ensure(req)
    return {"items": await eval_service.list_eval_sets(req.app.state.engine, req.state.tenant_id)}


@router.post("/sets", status_code=201)
async def create_eval_set(req_body: EvalSetIn, req: Request) -> dict[str, Any]:
    """新建自定义评估集。"""
    try:
        return await eval_service.create_eval_set(
            req.app.state.engine,
            req.state.tenant_id,
            kind=req_body.kind,
            name=req_body.name,
            description=req_body.description,
        )
    except eval_service.EvalError as exc:
        raise _to_http(exc) from exc


@router.get("/sets/{eval_set_id}")
async def get_eval_set(eval_set_id: str, req: Request) -> dict[str, Any]:
    """集合详情 + 用例列表。"""
    await _ensure(req)
    s = await eval_service.get_eval_set(req.app.state.engine, req.state.tenant_id, eval_set_id)
    if s is None:
        raise HTTPException(status_code=404, detail="评估集不存在")
    return s


@router.post("/sets/{eval_set_id}/cases", status_code=201)
async def add_eval_case(eval_set_id: str, req_body: EvalCaseIn, req: Request) -> dict[str, Any]:
    try:
        return await eval_service.add_eval_case(
            req.app.state.engine,
            req.state.tenant_id,
            eval_set_id,
            query=req_body.query,
            expected=req_body.expected,
            note=req_body.note,
        )
    except eval_service.EvalError as exc:
        raise _to_http(exc) from exc


@router.put("/cases/{case_id}")
async def update_eval_case(case_id: str, req_body: EvalCaseUpdate, req: Request) -> dict[str, Any]:
    try:
        out = await eval_service.update_eval_case(
            req.app.state.engine,
            req.state.tenant_id,
            case_id,
            query=req_body.query,
            expected=req_body.expected,
            note=req_body.note,
            enabled=req_body.enabled,
        )
    except eval_service.EvalError as exc:
        raise _to_http(exc) from exc
    if out is None:
        raise HTTPException(status_code=404, detail="用例不存在")
    return out


@router.delete("/cases/{case_id}")
async def delete_eval_case(case_id: str, req: Request) -> dict[str, Any]:
    ok = await eval_service.delete_eval_case(req.app.state.engine, req.state.tenant_id, case_id)
    if not ok:
        raise HTTPException(status_code=404, detail="用例不存在")
    return {"deleted": True}


@router.post("/sets/{eval_set_id}/runs", status_code=201)
async def start_eval_run(
    eval_set_id: str,
    req: Request,
    mode: str = Query(default="rules", pattern="^(rules|llm)$"),
) -> dict[str, Any]:
    """触发跑分（后台任务，D4）。mode=rules 规则层快速 / llm 真 LLM 升级。"""
    await _ensure(req)
    try:
        run = await eval_service.start_run(
            req.app.state.engine,
            req.state.tenant_id,
            req.state.user_id,
            eval_set_id,
            mode=mode,
        )
    except eval_service.EvalError as exc:
        raise _to_http(exc) from exc

    async def _background() -> None:
        await eval_service.run_eval_task(
            req.app.state.engine,
            req.state.tenant_id,
            run["run_id"],
            settings=req.app.state.settings,
            role_id=req.state.role_id,
        )

    asyncio.create_task(_background())
    return run


@router.post("/runs/{run_id}/cancel")
async def cancel_eval_run(run_id: str, req: Request) -> dict[str, Any]:
    """取消进行中的跑分（FDE 反馈：llm 模式可挂数小时）。

    running → cancelled（后台任务每 case 前检查后提前终止）；
    已完成/已取消 → 幂等返回当前态；不存在 → 404。
    """
    out = await eval_service.cancel_run(req.app.state.engine, req.state.tenant_id, run_id)
    if out is None:
        raise HTTPException(status_code=404, detail="跑分记录不存在")
    return out


@router.get("/runs")
async def list_eval_runs(
    req: Request,
    eval_set_id: str | None = None,
) -> dict[str, Any]:
    """跑分历史（可按评估集过滤）。"""
    await _ensure(req)
    return {"items": await eval_service.list_runs(req.app.state.engine, req.state.tenant_id, eval_set_id)}


@router.get("/runs/{run_id}")
async def get_eval_run(run_id: str, req: Request) -> dict[str, Any]:
    """跑分明细（+逐用例结果）。"""
    await _ensure(req)
    run = await eval_service.get_run(req.app.state.engine, req.state.tenant_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="跑分记录不存在")
    return run
