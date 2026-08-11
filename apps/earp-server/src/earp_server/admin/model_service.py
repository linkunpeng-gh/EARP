"""Model config service (PRD-2026-031) — CRUD + runtime model loading + test.

Layer 2 (model_configs) + Layer 3 (system_model_settings) operations.
Runtime: load_runtime_models() reads DB defaults, falls back to env Settings.
"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from earp_server.infra import credential_crypto, model_registry

logger = logging.getLogger(__name__)

VALID_TYPES = model_registry.MODEL_TYPES  # llm / embedding / rerank


async def create_model_config(
    engine: AsyncEngine,
    tenant_id: str,
    provider: str,
    model_type: str,
    model_name: str,
    credentials: dict,
) -> dict:
    if provider not in {p["provider"] for p in model_registry.list_providers()}:
        raise ValueError(f"unsupported provider: {provider}")
    if model_type not in VALID_TYPES:
        raise ValueError(f"unsupported model_type: {model_type}")
    if model_type not in model_registry.supported_model_types(provider):
        raise ValueError(f"provider {provider} does not support model_type {model_type}")

    config_id = f"mc-{uuid.uuid4().hex[:12]}"
    encrypted = credential_crypto.encrypt(credentials)
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        try:
            await conn.execute(
                text(
                    "INSERT INTO model_configs "
                    "(config_id, tenant_id, provider, model_type, model_name, credentials) "
                    "VALUES (:cid, :tid, :prov, :mtype, :mname, :cred)"
                ),
                {
                    "cid": config_id,
                    "tid": tenant_id,
                    "prov": provider,
                    "mtype": model_type,
                    "mname": model_name,
                    "cred": json.dumps(encrypted),
                },
            )
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise
    return {"config_id": config_id, "provider": provider, "model_type": model_type, "model_name": model_name}


async def list_model_configs(engine: AsyncEngine, tenant_id: str, model_type: str | None = None) -> list[dict]:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        sql = ("SELECT config_id, provider, model_type, model_name, enabled, is_default "
                "FROM model_configs WHERE tenant_id = :tid")
        params: dict = {"tid": tenant_id}
        if model_type:
            sql += " AND model_type = :mtype"
            params["mtype"] = model_type
        sql += " ORDER BY provider, model_name"
        rows = await conn.execute(text(sql), params)
        return [dict(r._mapping) for r in rows.fetchall()]


async def update_model_config(
    engine: AsyncEngine,
    tenant_id: str,
    config_id: str,
    *,
    credentials: dict | None = None,
    enabled: bool | None = None,
    is_default: bool | None = None,
) -> dict | None:
    sets: list[str] = []
    params: dict = {"cid": config_id, "tid": tenant_id}
    if credentials is not None:
        sets.append("credentials = :cred")
        params["cred"] = json.dumps(credential_crypto.encrypt(credentials))
    if enabled is not None:
        sets.append("enabled = :en")
        params["en"] = enabled
    if is_default is not None:
        sets.append("is_default = :df")
        params["df"] = is_default
    if not sets:
        return None
    sets.append("updated_at = now()")
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text(f"UPDATE model_configs SET {', '.join(sets)} WHERE config_id = :cid RETURNING config_id"),
            params,
        )
        await conn.commit()
        r = result.fetchone()
        return {"config_id": r.config_id} if r else None


async def delete_model_config(engine: AsyncEngine, tenant_id: str, config_id: str) -> tuple[bool, str | None]:
    """Returns (deleted, error). Refuses when the config is referenced by system_model_settings."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        ref = await conn.execute(
            text("SELECT setting_type FROM system_model_settings WHERE model_config_id = :cid"),
            {"cid": config_id},
        )
        if ref.fetchone() is not None:
            return False, "config is referenced as a default model — change the default first"
        result = await conn.execute(
            text("DELETE FROM model_configs WHERE config_id = :cid RETURNING config_id"),
            {"cid": config_id},
        )
        await conn.commit()
        return result.fetchone() is not None, None


async def get_system_model_settings(engine: AsyncEngine, tenant_id: str) -> dict:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        rows = await conn.execute(
            text(
                "SELECT s.setting_type, s.model_config_id, m.provider, m.model_name "
                "FROM system_model_settings s JOIN model_configs m ON m.config_id = s.model_config_id "
                "WHERE s.tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
        out: dict = {}
        for r in rows.fetchall():
            out[r.setting_type] = {
                "model_config_id": r.model_config_id,
                "provider": r.provider,
                "model_name": r.model_name,
            }
        return out


async def set_system_model_settings(engine: AsyncEngine, tenant_id: str, settings_map: dict[str, str]) -> dict:
    """settings_map: {llm: config_id, embedding: config_id, rerank: config_id}."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        for mtype, config_id in settings_map.items():
            if mtype not in VALID_TYPES:
                raise ValueError(f"invalid setting type: {mtype}")
            # verify config exists for this tenant
            exists = await conn.execute(
                text("SELECT 1 FROM model_configs WHERE config_id = :cid AND tenant_id = :tid"),
                {"cid": config_id, "tid": tenant_id},
            )
            if exists.fetchone() is None:
                raise ValueError(f"model config not found: {config_id}")
            await conn.execute(
                text(
                    "INSERT INTO system_model_settings (tenant_id, setting_type, model_config_id) "
                    "VALUES (:tid, :mtype, :cid) "
                    "ON CONFLICT (tenant_id, setting_type) DO UPDATE SET model_config_id = EXCLUDED.model_config_id, "
                    "updated_at = now()"
                ),
                {"tid": tenant_id, "mtype": mtype, "cid": config_id},
            )
        await conn.commit()
    return await get_system_model_settings(engine, tenant_id)


async def test_connection(engine: AsyncEngine, tenant_id: str, config_id: str) -> dict:
    """Real call to the model endpoint. Returns {ok, detail}."""
    creds = await _load_config_credentials(engine, tenant_id, config_id)
    if creds is None:
        return {"ok": False, "detail": "model config not found"}
    provider, model_type, model_name, credentials = creds
    try:
        if provider == "ollama":
            import httpx

            base_url = credentials.get("base_url", "http://localhost:11434").rstrip("/")
            endpoint = "/api/embed" if model_type == "embedding" else "/api/chat"
            payload = (
                {"model": model_name, "input": ["ping"]}
                if model_type == "embedding"
                else {"model": model_name, "messages": [{"role": "user", "content": "ping"}]}
            )
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(f"{base_url}{endpoint}", json=payload)
                resp.raise_for_status()
            return {"ok": True, "detail": f"{provider} {model_name} reachable"}
        if provider == "openai":
            import httpx

            base_url = credentials.get("base_url", "https://api.openai.com/v1").rstrip("/")
            api_key = credentials.get("api_key", "")
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{base_url}/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                resp.raise_for_status()
            return {"ok": True, "detail": f"openai {model_name} reachable"}
        return {"ok": False, "detail": f"unsupported provider: {provider}"}
    except Exception as e:  # noqa: BLE001 - surface connection errors to admin
        return {"ok": False, "detail": str(e)}


async def _load_config_credentials(
    engine: AsyncEngine, tenant_id: str, config_id: str
) -> tuple[str, str, str, dict] | None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT provider, model_type, model_name, credentials FROM model_configs WHERE config_id = :cid"),
            {"cid": config_id},
        )
        r = row.fetchone()
        if r is None:
            return None
        return r.provider, r.model_type, r.model_name, credential_crypto.decrypt(r.credentials)


async def load_runtime_models(engine: AsyncEngine, tenant_id: str) -> dict:
    """Runtime model map from DB defaults: {llm: {...}, embedding: {...}, rerank: ...}.
    Empty dict when nothing configured — caller falls back to env Settings.
    """
    settings_map = await get_system_model_settings(engine, tenant_id)
    out: dict = {}
    for mtype, s in settings_map.items():
        creds = await _load_config_credentials(engine, tenant_id, s["model_config_id"])
        if creds is None:
            continue
        provider, _t, model_name, credentials = creds
        out[mtype] = {"provider": provider, "model_name": model_name, **credentials}
    return out
