"""PRD-2026-031 — model config CRUD + encryption + system settings + runtime load."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from earp_server.admin import model_service
from earp_server.infra import credential_crypto


@pytest.fixture(scope="module")
def app_engine(migrated: str, app_url: str) -> AsyncEngine:
    return create_async_engine(app_url, pool_pre_ping=True)


async def test_create_config_encrypted_and_unique(app_engine: AsyncEngine) -> None:
    tid = "mc-t1"
    created = await model_service.create_model_config(
        app_engine, tid, "ollama", "llm", "qwen3.6:35b", {"base_url": "http://localhost:11434"}
    )
    assert created["config_id"].startswith("mc-")

    # credentials must be encrypted in DB (no plaintext base_url), masked in list
    async with app_engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tid}'"))
        row = await conn.execute(
            text("SELECT credentials FROM model_configs WHERE config_id = :cid"), {"cid": created["config_id"]}
        )
        raw = row.fetchone().credentials  # JSONB already parsed by driver
        assert "ciphertext" in raw and "base_url" not in raw
        assert credential_crypto.decrypt(raw)["base_url"] == "http://localhost:11434"

    # unique (tenant, provider, type, name) violation
    import sqlalchemy.exc as sa_exc

    with pytest.raises(sa_exc.IntegrityError):
        await model_service.create_model_config(app_engine, tid, "ollama", "llm", "qwen3.6:35b", {})

    # unsupported provider / type rejected
    with pytest.raises(ValueError):
        await model_service.create_model_config(app_engine, tid, "unknown", "llm", "x", {})
    with pytest.raises(ValueError):
        await model_service.create_model_config(app_engine, tid, "ollama", "rerank", "x", {})  # ollama has no rerank


async def test_system_settings_and_delete_guard(app_engine: AsyncEngine) -> None:
    tid = "mc-t2"
    llm = await model_service.create_model_config(app_engine, tid, "ollama", "llm", "qwen3.6:35b", {})
    emb = await model_service.create_model_config(app_engine, tid, "ollama", "embedding", "bge-m3:latest", {})

    settings = await model_service.set_system_model_settings(
        app_engine, tid, {"llm": llm["config_id"], "embedding": emb["config_id"], "copilot": llm["config_id"]}
    )
    assert settings["llm"]["model_name"] == "qwen3.6:35b"
    assert settings["embedding"]["model_name"] == "bge-m3:latest"
    # copilot (AI 助手专用模型) 作为合法 setting_type 可持久化（migration 0030 放宽 CHECK）
    assert settings["copilot"]["model_name"] == "qwen3.6:35b"

    # delete referenced config → refused
    deleted, error = await model_service.delete_model_config(app_engine, tid, llm["config_id"])
    assert deleted is False and error is not None

    # delete unreferenced config → ok
    extra = await model_service.create_model_config(app_engine, tid, "ollama", "llm", "llama3", {})
    deleted, error = await model_service.delete_model_config(app_engine, tid, extra["config_id"])
    assert deleted is True and error is None

    # invalid setting type
    with pytest.raises(ValueError):
        await model_service.set_system_model_settings(app_engine, tid, {"stt": llm["config_id"]})


async def test_load_runtime_models_fallback(app_engine: AsyncEngine) -> None:
    """No DB config → empty map (caller falls back to env)."""
    assert await model_service.load_runtime_models(app_engine, "mc-empty") == {}

    tid = "mc-t3"
    llm = await model_service.create_model_config(
        app_engine, tid, "ollama", "llm", "qwen3.6:35b", {"base_url": "http://x:11434"}
    )
    await model_service.set_system_model_settings(app_engine, tid, {"llm": llm["config_id"]})
    runtime = await model_service.load_runtime_models(app_engine, tid)
    assert runtime["llm"]["model_name"] == "qwen3.6:35b"
    assert runtime["llm"]["base_url"] == "http://x:11434"


async def test_test_connection_ollama_ok(app_engine: AsyncEngine, monkeypatch) -> None:
    tid = "mc-t4"

    class _FakeResp:
        def raise_for_status(self) -> None:
            pass

    async def _fake_post(self, url, json=None):
        assert "11434" in url
        return _FakeResp()

    import httpx

    monkeypatch.setattr(httpx.AsyncClient, "post", _fake_post)
    cfg = await model_service.create_model_config(
        app_engine, tid, "ollama", "llm", "qwen3.6:35b", {"base_url": "http://localhost:11434"}
    )
    result = await model_service.test_connection(app_engine, tid, cfg["config_id"])
    assert result["ok"] is True

    # not-found config
    assert (await model_service.test_connection(app_engine, tid, "mc-nope"))["ok"] is False
