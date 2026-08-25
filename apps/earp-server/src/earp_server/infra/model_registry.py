"""Model provider catalog (Layer 1 — Dify model_runtime reference).

Static builtin providers (ollama + openai in Phase 1). Extend for
anthropic/qwen/zhipu in Phase 2 by adding entries + connector support.
"""

from __future__ import annotations

MODEL_TYPES: tuple[str, ...] = ("llm", "embedding", "rerank", "copilot")  # rerank/copilot are placeholders

MODEL_PROVIDERS: list[dict] = [
    {
        "provider": "ollama",
        "name": "Ollama",
        "model_types": ["llm", "embedding", "copilot"],
        "credential_schema": [
            {"key": "base_url", "type": "string", "default": "http://localhost:11434", "required": True},
        ],
        "default_models": {"llm": "qwen3.6:35b", "embedding": "bge-m3:latest", "copilot": "qwen2.5:1.5b"},
    },
    {
        "provider": "openai",
        "name": "OpenAI",
        "model_types": ["llm", "embedding", "copilot"],
        "credential_schema": [
            {"key": "api_key", "type": "secret", "required": True},
            {"key": "base_url", "type": "string", "optional": True, "default": "https://api.openai.com/v1"},
        ],
        "default_models": {"llm": "gpt-4o", "embedding": "text-embedding-3-small", "copilot": "gpt-4o-mini"},
    },
]

_PROVIDER_MAP: dict[str, dict] = {p["provider"]: p for p in MODEL_PROVIDERS}


def get_provider(provider: str) -> dict | None:
    return _PROVIDER_MAP.get(provider)


def list_providers() -> list[dict]:
    return [dict(p) for p in MODEL_PROVIDERS]


def supported_model_types(provider: str) -> list[str]:
    p = get_provider(provider)
    return list(p["model_types"]) if p else []
