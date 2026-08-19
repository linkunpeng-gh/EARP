"""chat_apps CRUD + publish state machine + audit events.

P1 问答链路一期 — arch/design/2026-08-11-chat-agent-design.md §4.2/§4.6.

- create: draft
- update: published → 自动回 draft（需重新测试发布）
- delete: 硬删（会话经 ON DELETE SET NULL 保留）
- publish: draft → published（审计）
- 审计事件：earp.chat_app.created / updated / deleted / published
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra.eventbus import CloudEvent
from earp_server.orchestrator.workflow_dsl import validate_flow_schema

_VALID_MODES = ("vector", "hybrid")
_ORCHESTRATIONS = ("auto", "flow")
_DEFAULT_RETRIEVAL = {"mode": "hybrid", "top_k": 5, "threshold": 0.0}
_DEFAULT_GENERATION = {"temperature": 0.7, "top_p": 0.9, "max_tokens": 1024}
_STATUSES = ("draft", "published")
_UPDATABLE = (
    "name",
    "description",
    "system_prompt",
    "kb_scope",
    "retrieval",
    "generation",
    "model_config_id",
    "context_turns",
    "orchestration",
    "flow_schema",
)


def _audit(bus, event_type: str, tenant_id: str, user_id: str, chat_app_id: str, extra: dict | None = None) -> None:
    if bus is None:
        return
    data = {
        "entity_type": "chat_app",
        "entity_id": chat_app_id,
        "user_id": user_id,
        **(extra or {}),
    }
    bus.publish(
        CloudEvent(
            type=event_type,
            source="earp-server/conversation",
            tenant_id=tenant_id,
            data=data,
        )
    )


def _validate_retrieval(retrieval: dict[str, Any] | None) -> dict[str, Any]:
    r = {**_DEFAULT_RETRIEVAL, **(retrieval or {})}
    if r["mode"] not in _VALID_MODES:
        raise ValueError(f"retrieval.mode must be one of {_VALID_MODES}")
    r["top_k"] = max(1, min(50, int(r.get("top_k", 5))))
    r["threshold"] = max(0.0, min(1.0, float(r.get("threshold", 0.0))))
    return r


async def _check_model_config(engine: AsyncEngine, tenant_id: str, config_id: str | None) -> None:
    """422-pre-check: referenced model config must exist and belong to this tenant."""
    if not config_id:
        return
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT 1 FROM model_configs WHERE config_id = :cid AND tenant_id = :tid"),
            {"cid": config_id, "tid": tenant_id},
        )
        if row.fetchone() is None:
            raise ValueError(f"model config not found or not owned by tenant: {config_id}")


def _jsonb(v):
    """JSONB → Python（psycopg 3 通常自动解析，防御 str 形态）。"""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return None
    return v


def _validate_generation(generation: dict[str, Any] | None) -> dict[str, Any]:
    """生成参数校验：temperature 0-2 / top_p 0-1 / max_tokens 128-8192（Ollama options 对齐）。"""
    g = {**_DEFAULT_GENERATION, **(generation or {})}
    g["temperature"] = max(0.0, min(2.0, float(g.get("temperature", 0.7))))
    g["top_p"] = max(0.0, min(1.0, float(g.get("top_p", 0.9))))
    g["max_tokens"] = max(128, min(8192, int(g.get("max_tokens", 1024))))
    return g


def _check_flow_fields(app: dict[str, Any] | None, fields: dict[str, Any]) -> None:
    """Chatflow F1: orchestration/flow_schema 校验。

    - orchestration ∈ {auto, flow}
    - flow 模式：flow_schema 必填（非空 dict）且通过图校验（复用 F0 validate_workflow）
    - auto 模式：flow_schema 传了也校验（坏图存不进去；切回 flow 不重画）
    """
    orchestration = fields.get("orchestration", (app or {}).get("orchestration", "auto"))
    if orchestration not in _ORCHESTRATIONS:
        raise ValueError(f"orchestration must be one of {_ORCHESTRATIONS}")
    schema = fields.get("flow_schema", (app or {}).get("flow_schema"))
    if orchestration == "flow":
        if not isinstance(schema, dict) or not schema:
            raise ValueError("flow_schema is required when orchestration='flow'")
    if schema is not None and not isinstance(schema, dict):
        raise ValueError("flow_schema must be an object")
    if isinstance(schema, dict) and schema:
        errors = validate_flow_schema(schema)
        if errors:
            raise ValueError("invalid flow_schema: " + "; ".join(errors))


def _row_to_dict(row) -> dict[str, Any]:
    d = dict(row._mapping)
    d["kb_scope"] = _jsonb(d.get("kb_scope")) or []
    d["retrieval"] = _jsonb(d.get("retrieval")) or dict(_DEFAULT_RETRIEVAL)
    d["generation"] = _jsonb(d.get("generation")) or dict(_DEFAULT_GENERATION)
    d["flow_schema"] = _jsonb(d.get("flow_schema"))
    return d


async def create_chat_app(
    engine: AsyncEngine,
    tenant_id: str,
    user_id: str,
    name: str,
    description: str = "",
    *,
    bus=None,
    system_prompt: str | None = None,
    orchestration: str = "auto",
    flow_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a chat agent (status=draft). name is required (前端新建模态已校验)."""
    name = (name or "").strip()
    if not name:
        raise ValueError("name is required")
    _check_flow_fields(None, {"orchestration": orchestration, "flow_schema": flow_schema})
    chat_app_id = f"app-{uuid.uuid4().hex[:12]}"
    flow_json = json.dumps(flow_schema) if flow_schema is not None else None
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        if system_prompt is None:
            # 不传 → 用 DB 默认模板（migration 0014 DEFAULT）
            await conn.execute(
                text(
                    "INSERT INTO chat_apps (chat_app_id, tenant_id, name, description, "
                    "orchestration, flow_schema, created_at, updated_at) "
                    "VALUES (:id, :tid, :name, :desc, :orch, :flow, now(), now())"
                ),
                {
                    "id": chat_app_id,
                    "tid": tenant_id,
                    "name": name,
                    "desc": description.strip(),
                    "orch": orchestration,
                    "flow": flow_json,
                },
            )
        else:
            await conn.execute(
                text(
                    "INSERT INTO chat_apps (chat_app_id, tenant_id, name, description, system_prompt, "
                    "orchestration, flow_schema, created_at, updated_at) "
                    "VALUES (:id, :tid, :name, :desc, :prompt, :orch, :flow, now(), now())"
                ),
                {
                    "id": chat_app_id,
                    "tid": tenant_id,
                    "name": name,
                    "desc": description.strip(),
                    "prompt": system_prompt,
                    "orch": orchestration,
                    "flow": flow_json,
                },
            )
        await conn.commit()
    _audit(bus, "earp.chat_app.created", tenant_id, user_id, chat_app_id, {"name": name})
    return await get_chat_app(engine, tenant_id, chat_app_id) or {"chat_app_id": chat_app_id, "name": name}


async def list_chat_apps(engine: AsyncEngine, tenant_id: str) -> list[dict[str, Any]]:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT chat_app_id, name, description, status, orchestration, created_at, updated_at "
                "FROM chat_apps WHERE tenant_id = :tid ORDER BY created_at DESC"
            ),
            {"tid": tenant_id},
        )
        return [_row_to_dict(r) for r in rows]


async def get_chat_app(engine: AsyncEngine, tenant_id: str, chat_app_id: str) -> dict[str, Any] | None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = (
            await conn.execute(
                text("SELECT * FROM chat_apps WHERE chat_app_id = :id AND tenant_id = :tid"),
                {"id": chat_app_id, "tid": tenant_id},
            )
        ).first()
        return _row_to_dict(row) if row else None


async def update_chat_app(
    engine: AsyncEngine,
    tenant_id: str,
    user_id: str,
    chat_app_id: str,
    fields: dict[str, Any],
    *,
    bus=None,
) -> dict[str, Any] | None:
    """Update a chat agent. Editing a published app reverts it to draft (需重新发布)."""
    app = await get_chat_app(engine, tenant_id, chat_app_id)
    if app is None:
        return None

    # Chatflow F1: orchestration/flow_schema 校验（合并库内现值：切 flow 时用已有 schema）
    if "orchestration" in fields or "flow_schema" in fields:
        _check_flow_fields(app, fields)

    sets: list[str] = []
    params: dict[str, Any] = {"id": chat_app_id, "tid": tenant_id}
    for key in _UPDATABLE:
        if key not in fields:
            continue
        val = fields[key]
        # None 视为未提供：仅 model_config_id 允许显式 null（清空引用）
        if val is None and key != "model_config_id":
            continue
        if key == "retrieval":
            val = _validate_retrieval(val)
            val = json.dumps(val)
            sets.append("retrieval = :retrieval")
            params["retrieval"] = val
        elif key == "generation":
            val = _validate_generation(val)
            val = json.dumps(val)
            sets.append("generation = :generation")
            params["generation"] = val
        elif key == "kb_scope":
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                raise ValueError("kb_scope must be a list of KB ids")
            sets.append("kb_scope = :kb_scope")
            params["kb_scope"] = json.dumps(val)
        elif key == "model_config_id":
            await _check_model_config(engine, tenant_id, val)
            sets.append("model_config_id = :model_config_id")
            params["model_config_id"] = val
        elif key == "orchestration":
            sets.append("orchestration = :orchestration")
            params["orchestration"] = val
        elif key == "flow_schema":
            sets.append("flow_schema = :flow_schema")
            params["flow_schema"] = json.dumps(val)
        elif key == "context_turns":
            sets.append("context_turns = :context_turns")
            params["context_turns"] = max(1, min(20, int(val)))
        elif key == "name":
            val = (val or "").strip()
            if not val:
                raise ValueError("name is required")
            sets.append("name = :name")
            params["name"] = val
        else:
            sets.append(f"{key} = :{key}")
            params[key] = val

    # CP 决策：编辑已发布应用 → 回 draft（需重新发布）
    status_changed = False
    if app["status"] == "published":
        sets.append("status = 'draft'")
        status_changed = True

    if not sets:
        return app
    sets.append("updated_at = now()")

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(text(f"UPDATE chat_apps SET {', '.join(sets)} WHERE chat_app_id = :id"), params)
        await conn.commit()

    _audit(
        bus,
        "earp.chat_app.updated",
        tenant_id,
        user_id,
        chat_app_id,
        {"reverted_to_draft": status_changed},
    )
    return await get_chat_app(engine, tenant_id, chat_app_id)


async def delete_chat_app(engine: AsyncEngine, tenant_id: str, user_id: str, chat_app_id: str, *, bus=None) -> bool:
    app = await get_chat_app(engine, tenant_id, chat_app_id)
    if app is None:
        return False
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(text("DELETE FROM chat_apps WHERE chat_app_id = :id"), {"id": chat_app_id})
        await conn.commit()
    _audit(bus, "earp.chat_app.deleted", tenant_id, user_id, chat_app_id, {"name": app.get("name")})
    return True


async def publish_chat_app(
    engine: AsyncEngine, tenant_id: str, user_id: str, chat_app_id: str, *, bus=None
) -> dict[str, Any] | None:
    """draft → published. Idempotent: already-published returns current state.

    Chatflow F1: orchestration='flow' 时强制重校验 flow_schema（发布评审覆盖
    flow 变更——设计稿 §9 开放问题 1 落地）；校验失败拒绝发布。
    """
    app = await get_chat_app(engine, tenant_id, chat_app_id)
    if app is None:
        return None
    if app["status"] != "published":
        _check_flow_fields(app, {})
        async with engine.connect() as conn:
            await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
            await conn.execute(
                text("UPDATE chat_apps SET status = 'published', updated_at = now() WHERE chat_app_id = :id"),
                {"id": chat_app_id},
            )
            await conn.commit()
        _audit(bus, "earp.chat_app.published", tenant_id, user_id, chat_app_id, {"name": app.get("name")})
    return await get_chat_app(engine, tenant_id, chat_app_id)
