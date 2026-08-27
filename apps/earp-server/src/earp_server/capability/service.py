"""Capability 注册 / 管理（tech-debt #14）+ execution 声明字段（通用执行器任务书 D1）。

- create_capability / get_capability / update_capability / deprecate_capability
- 门禁由端点层（admin）把控；校验（type / schema / permissions / execution）在此
- 审计事件 earp.capability.registered/updated/deprecated（entity_type=capability）
- list 复用 registry.discover（语义搜索 + 角色可见性过滤）
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.capability.registry import EXECUTION_ADAPTERS
from earp_server.infra.eventbus import CloudEvent

if TYPE_CHECKING:
    from earp_server.infra.eventbus import EventBus

logger = logging.getLogger(__name__)


class CapabilityConflictError(Exception):
    """同 (capability_id, tenant_id) 已存在 —— 端点映射 409（区别于校验错误 422）。"""


# capability_id 字符白名单：小写字母/数字/横杠/下划线，小写字母数字开头
# （存量的 XSS 注入面根治：id 会进前端 onclick 内联 JS 与 f-string SQL 上下文）
_CAP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_CAP_ID_MAX = 64  # DDL VARCHAR(64)
_DOMAIN_MAX = 64  # DDL VARCHAR(64)
_VERSION_MAX = 16  # DDL VARCHAR(16)

_VALID_TYPES = ("query", "command")
_STATUS_ACTIVE = "active"
_STATUS_DEPRECATED = "deprecated"


def _slug(s: str) -> str:
    s = (s or "").strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-") or "x"


def _validate_cap_id(cap_id: str) -> str:
    """capability_id 校验：非空 ≤ 64 + 字符白名单（防注入面 + DB 长度，2026-08-21 review 修复 #1/#3）。"""
    if not cap_id or not cap_id.strip():
        raise ValueError("capability_id 不能为空")
    if len(cap_id) > _CAP_ID_MAX:
        raise ValueError(f"capability_id 长度不能超过 {_CAP_ID_MAX}（当前 {len(cap_id)}）")
    if not _CAP_ID_RE.fullmatch(cap_id):
        raise ValueError("capability_id 只能包含小写字母/数字/横杠/下划线，且以字母或数字开头")
    return cap_id


def _validate_text_field(value: str, field: str, max_len: int) -> str:
    """非空 + 长度校验（VARCHAR 列，防 DB DataError → 500）。"""
    v = (value or "").strip()
    if not v:
        raise ValueError(f"{field} 不能为空")
    if len(v) > max_len:
        raise ValueError(f"{field} 长度不能超过 {max_len}（当前 {len(v)}）")
    return v


def _validate_json_schema(schema: Any, field: str) -> None:
    """轻量 JSON Schema 校验：合法 JSON 对象 + 含 properties 结构（不引 jsonschema 大库，D6）。"""
    if not isinstance(schema, dict):
        raise ValueError(f"{field} 必须是 JSON 对象")
    if "properties" not in schema or not isinstance(schema["properties"], dict):
        raise ValueError(f"{field} 必须含 properties 对象")


def _validate_execution(execution: Any) -> None:
    """execution 格式校验：{{adapter, params?}}——adapter ∈ 白名单；未知仅 warning（执行器任务书再严判）。"""
    if execution is None:
        return
    if not isinstance(execution, dict):
        raise ValueError("execution 必须是 JSON 对象")
    adapter = execution.get("adapter")
    if adapter is not None and adapter not in EXECUTION_ADAPTERS:
        logger.warning(
            "capability execution adapter %r 不在白名单 %s（注册允许，执行时再判）",
            adapter,
            sorted(EXECUTION_ADAPTERS),
        )
    params = execution.get("params")
    if params is not None and not isinstance(params, dict):
        raise ValueError("execution.params 必须是 JSON 对象")


def _audit(
    bus: EventBus | None,
    event_type: str,
    tenant_id: str,
    user_id: str,
    capability_id: str,
    extra: dict[str, Any] | None = None,
) -> None:
    if bus is None:
        return
    data = {
        "entity_type": "capability",
        "entity_id": capability_id,
        "user_id": user_id,
        **(extra or {}),
    }
    bus.publish(
        CloudEvent(
            type=event_type,
            source="earp-server/capability",
            tenant_id=tenant_id,
            data=data,
        )
    )


def _row_to_dict(r: Any) -> dict[str, Any]:
    d = dict(r._mapping)
    # JSONB 防御：psycopg3 已解析，str 形态回退
    for col in ("input_schema", "output_schema", "execution"):
        v = d.get(col)
        if isinstance(v, str):
            try:
                d[col] = json.loads(v)
            except (TypeError, ValueError):
                d[col] = {}
    d["required_permissions"] = list(d.get("required_permissions") or [])
    d["visible_roles"] = list(d.get("visible_roles") or [])
    return d


async def get_capability(engine: AsyncEngine, tenant_id: str, capability_id: str) -> dict[str, Any] | None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text(
                "SELECT capability_id, tenant_id, domain, name, type, input_schema, output_schema, "
                "required_permissions, visible_roles, version, status, execution, created_at "
                "FROM business_capabilities WHERE capability_id = :cid AND tenant_id = :tid"
            ),
            {"cid": capability_id, "tid": tenant_id},
        )
        r = row.fetchone()
        return _row_to_dict(r) if r else None


async def capability_visible_to_role(engine: AsyncEngine, tenant_id: str, capability_id: str, role_id: str) -> bool:
    """详情端点角色可见性（2026-08-21 review 修复 #4）：与 discover 列表过滤同构
    （required_permissions ⊆ role.permissions）+ is_admin 豁免 —— 列表看不见的能力，
    知道 id 也不能拿全量声明（含 execution.params 内部基础设施标识）。
    """
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text(
                "SELECT 1 FROM business_capabilities c, roles r "
                "WHERE c.capability_id = :cid AND c.tenant_id = :tid "
                "AND r.role_id = :rid AND r.tenant_id = :tid "
                "AND (r.is_admin OR c.required_permissions <@ r.permissions)"
            ),
            {"cid": capability_id, "tid": tenant_id, "rid": role_id},
        )
        return row.fetchone() is not None


async def create_capability(
    engine: AsyncEngine,
    tenant_id: str,
    *,
    domain: str,
    name: str,
    type: str,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    required_permissions: list[str] | None = None,
    version: str = "1.0.0",
    execution: dict[str, Any] | None = None,
    visible_roles: list[str] | None = None,
    capability_id: str | None = None,
    bus: EventBus | None = None,
    user_id: str = "",
) -> dict[str, Any]:
    type = (type or "").strip()
    if type not in _VALID_TYPES:
        raise ValueError(f"type 必须是 {_VALID_TYPES} 之一")
    domain = _validate_text_field(domain, "domain", _DOMAIN_MAX)
    name = _validate_text_field(name, "name", 512)  # name 为 TEXT 列，只查非空
    version = _validate_text_field(version, "version", _VERSION_MAX)
    # 缺省为最小合法 JSON Schema（含 properties）——调用方无需每次手写
    in_schema = input_schema if input_schema is not None else {"type": "object", "properties": {}}
    out_schema = output_schema if output_schema is not None else {"type": "object", "properties": {}}
    _validate_json_schema(in_schema, "input_schema")
    _validate_json_schema(out_schema, "output_schema")
    perms = list(required_permissions or [])
    if not perms:
        raise ValueError("required_permissions 不能为空（能力侧权限缺口，tech-debt #14）")
    _validate_execution(execution)
    # 自动生成 id 截断到安全长度（保证 ≤ 64，不依赖用户输入长度）
    cap_id = capability_id or f"cap-{_slug(domain)[:24]}-{_slug(name)[:32]}"
    _validate_cap_id(cap_id)

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        # 原子幂等（2026-08-21 review 修复 #5：SELECT→INSERT 两步的 TOCTOU 并发窗口）：
        # ON CONFLICT DO NOTHING + rowcount 判重，冲突 → CapabilityConflictError → 端点 409
        res = await conn.execute(
            text(
                "INSERT INTO business_capabilities "
                "(capability_id, tenant_id, domain, name, type, input_schema, output_schema, "
                "required_permissions, visible_roles, version, status, execution) "
                "VALUES (:cid, :tid, :domain, :name, :type, :input_schema, :output_schema, "
                ":perms, :vroles, :version, :status, :execution) "
                "ON CONFLICT (capability_id, tenant_id) DO NOTHING"
            ),
            {
                "cid": cap_id,
                "tid": tenant_id,
                "domain": domain,
                "name": name,
                "type": type,
                "input_schema": json.dumps(in_schema),
                "output_schema": json.dumps(out_schema),
                "perms": perms,
                "vroles": list(visible_roles or []),
                "version": version,
                "status": _STATUS_ACTIVE,
                "execution": json.dumps(execution or {}),
            },
        )
        if res.rowcount == 0:
            raise CapabilityConflictError(f"capability {cap_id!r} 已存在（tenant {tenant_id}）")
        await conn.commit()

    _audit(bus, "earp.capability.registered", tenant_id, user_id, cap_id, {"domain": domain, "name": name})
    return await get_capability(engine, tenant_id, cap_id)  # type: ignore[return-value]


async def update_capability(
    engine: AsyncEngine,
    tenant_id: str,
    capability_id: str,
    *,
    domain: str | None = None,
    name: str | None = None,
    type: str | None = None,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    required_permissions: list[str] | None = None,
    version: str | None = None,
    execution: dict[str, Any] | None = None,
    visible_roles: list[str] | None = None,
    bus: EventBus | None = None,
    user_id: str = "",
) -> dict[str, Any] | None:
    existing = await get_capability(engine, tenant_id, capability_id)
    if existing is None:
        return None
    if existing["status"] != _STATUS_ACTIVE:
        raise ValueError(f"capability {capability_id!r} 已停用，不可更新（soft-disable）")

    type = (type if type is not None else existing["type"]).strip()
    if type not in _VALID_TYPES:
        raise ValueError(f"type 必须是 {_VALID_TYPES} 之一")
    domain = _validate_text_field(domain if domain is not None else existing["domain"], "domain", _DOMAIN_MAX)
    name = _validate_text_field(name if name is not None else existing["name"], "name", 512)
    version = _validate_text_field(version if version is not None else existing["version"], "version", _VERSION_MAX)
    _validate_json_schema(input_schema if input_schema is not None else existing["input_schema"], "input_schema")
    _validate_json_schema(output_schema if output_schema is not None else existing["output_schema"], "output_schema")
    perms = list(required_permissions) if required_permissions is not None else existing["required_permissions"]
    if not perms:
        raise ValueError("required_permissions 不能为空")
    _validate_execution(execution)

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "UPDATE business_capabilities SET "
                "domain = :domain, name = :name, type = :type, "
                "input_schema = :input_schema, output_schema = :output_schema, "
                "required_permissions = :perms, visible_roles = :vroles, "
                "version = :version, execution = :execution "
                "WHERE capability_id = :cid AND tenant_id = :tid"
            ),
            {
                "domain": domain,
                "name": name,
                "type": type,
                "input_schema": json.dumps(input_schema if input_schema is not None else existing["input_schema"]),
                "output_schema": json.dumps(output_schema if output_schema is not None else existing["output_schema"]),
                "perms": perms,
                "vroles": list(visible_roles) if visible_roles is not None else existing["visible_roles"],
                "version": version,
                "execution": json.dumps(execution if execution is not None else existing["execution"]),
                "cid": capability_id,
                "tid": tenant_id,
            },
        )
        await conn.commit()

    _audit(bus, "earp.capability.updated", tenant_id, user_id, capability_id)
    return await get_capability(engine, tenant_id, capability_id)  # type: ignore[return-value]


async def deprecate_capability(
    engine: AsyncEngine,
    tenant_id: str,
    capability_id: str,
    *,
    bus: EventBus | None = None,
    user_id: str = "",
) -> dict[str, Any] | None:
    existing = await get_capability(engine, tenant_id, capability_id)
    if existing is None:
        return None
    if existing["status"] == _STATUS_DEPRECATED:
        return existing  # idempotent

    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text("UPDATE business_capabilities SET status = :status WHERE capability_id = :cid AND tenant_id = :tid"),
            {"status": _STATUS_DEPRECATED, "cid": capability_id, "tid": tenant_id},
        )
        await conn.commit()

    _audit(bus, "earp.capability.deprecated", tenant_id, user_id, capability_id)
    return await get_capability(engine, tenant_id, capability_id)  # type: ignore[return-value]
