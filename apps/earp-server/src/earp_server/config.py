"""Application settings (pydantic-settings). Env prefix: EARP_."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


def psycopg_dsn(sqlalchemy_url: str) -> str:
    """Convert a SQLAlchemy URL (postgresql+psycopg://) to a plain libpq DSN."""
    return sqlalchemy_url.replace("postgresql+psycopg://", "postgresql://", 1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EARP_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://earp_app:earp_app@localhost:5433/earp"
    migration_database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5433/earp"
    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    api_host: str = "127.0.0.1"
    api_port: int = 8000

    # ── Embedding ──
    ollama_base_url: str = "http://10.188.2.230:11434"
    ollama_embedding_model: str = "bge-m3:latest"
    ollama_chat_model: str = "qwen3.6:35b"
    embedding_dim: int = 1024  # bge-m3 dimension; change when switching models

    # ── LLM Cache ──
    llm_cache_ttl: int = 3600  # seconds (1 hour)
