"""Embedding provider abstraction — reference Dify core/rag/models/ pattern.

Supports Ollama (bge-m3) and OpenAI (text-embedding-3-small) out of the box.
Extend by subclassing EmbeddingProvider and registering in _PROVIDERS.
"""

from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING, ClassVar

import httpx

if TYPE_CHECKING:
    from earp_server.config import Settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(abc.ABC):
    """Abstract embedding provider. Subclass must implement _embed()."""

    name: ClassVar[str] = ""  # provider key, e.g. "ollama"
    dim: ClassVar[int] = 1024  # output dimension

    @abc.abstractmethod
    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Must return len(texts) embeddings."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        embs = await self._embed(texts)
        if len(embs) != len(texts):
            raise RuntimeError(f"Expected {len(texts)} embeddings, got {len(embs)}")
        return embs


class OllamaEmbeddingProvider(EmbeddingProvider):
    name = "ollama"
    dim = 1024  # bge-m3

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "bge-m3:latest"):
        self._url = f"{base_url}/api/embed"
        self._model = model

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        # 30s cap: embedding is fast (<2s) on a healthy server; a hung upstream
        # must fail fast so saves/rebuilds never block for minutes (2026-08-10).
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self._url, json={"model": self._model, "input": texts})
            resp.raise_for_status()
        return resp.json()["embeddings"]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
        dim: int | None = None,
    ):
        self._api_key = api_key
        self._model = model
        self._base_url = base_url or "https://api.openai.com/v1"
        # dim is model-dependent (bge-m3 = 1024, text-embedding-3-small = 1536)
        self.dim: int = dim or self._default_dim(model)

    @staticmethod
    def _default_dim(model: str) -> int:
        if "bge-m3" in model.lower() or "bge" in model.lower():
            return 1024
        return 1536

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        url = f"{self._base_url}/embeddings"
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json={"model": self._model, "input": texts}, headers=headers)
            resp.raise_for_status()
        data = resp.json()
        return [d["embedding"] for d in data["data"]]


def init_app(settings: Settings) -> None:
    """Startup hook — initialize the embedding provider from settings."""
    init_embedding_provider(
        provider=settings.embedding_provider,
        ollama_base_url=settings.ollama_base_url,
        ollama_model=settings.ollama_embedding_model,
        openai_api_key=settings.openai_api_key if hasattr(settings, "openai_api_key") else "",
    )


# ---------------------------------------------------------------------------
# Factory — called once at startup, stored as module-level singleton
_provider: EmbeddingProvider | None = None


def init_embedding_provider(
    provider: str = "ollama",
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "bge-m3:latest",
    openai_api_key: str = "",
    openai_model: str = "text-embedding-3-small",
    openai_base_url: str = "https://api.openai.com/v1",
) -> EmbeddingProvider:
    global _provider
    if provider == "ollama":
        _provider = OllamaEmbeddingProvider(base_url=ollama_base_url, model=ollama_model)
    elif provider == "openai":
        _provider = OpenAIEmbeddingProvider(
            api_key=openai_api_key, model=openai_model, base_url=openai_base_url
        )
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")
    logger.info("init_embedding_provider: %s (dim=%d)", provider, _provider.dim)
    return _provider


def get_embedding_provider() -> EmbeddingProvider:
    if _provider is None:
        raise RuntimeError("embedding provider not initialized — call init_embedding_provider() first")
    return _provider


def embedding_dim() -> int:
    return get_embedding_provider().dim
