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

    # ── CORS ──
    # Comma-separated allowed origins for browser cross-origin access.
    # Empty = allow all (dev/test default). Prod should set e.g. "https://admin.example.com".
    cors_origins: str = ""

    # ── Embedding ──
    ollama_base_url: str = "http://10.188.2.230:11434"
    ollama_embedding_model: str = "bge-m3:latest"
    embedding_provider: str = "ollama"  # ollama | openai
    # P3 rerank（enterprise-retrieval §8 Phase 2 ⑧）：默认禁用——本地 Ollama 旧版无
    # /api/rerank，provider 不可用时检索优雅降级为纯 RRF。
    rerank_provider: str = "none"  # none | ollama | openai（兼容 /rerank）
    ollama_rerank_model: str = "bge-reranker-v2-m3"
    rerank_top_n: int = 20  # 精排候选数（RRF/向量召回后）
    ollama_chat_model: str = "qwen3.6:27b"
    embedding_dim: int = 1024  # bge-m3 dimension; change when switching models

    # ── LLM Cache ──
    llm_cache_ttl: int = 3600  # seconds (1 hour)

    # ── Eval run stale recovery (T1 D2) ──
    # running 任务心跳超过该时长 → worker 启动标记 failed（interrupted）。
    # 心跳方案：job 内每 case 更新 heartbeat_at；勿回退 started_at 一刀切
    # （llm 跑分 111 例 × 30s 超时 ≈ 55min，TTL=1h 会误杀合法在跑任务）。
    eval_run_ttl: int = 3600  # seconds (EARP_EVAL_RUN_TTL)

    # ── Observability (M15) ──
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"
