"""Reranker provider abstraction — cross-encoder re-ranking (P3, enterprise-retrieval §8 Phase 2 ⑧).

Supports Ollama /api/rerank (v0.9.5+) and OpenAI-compatible /rerank (Jina/Cohere/DashScope
style: {model, query, documents} → results[{index, relevance_score}]).
Default disabled (rerank_provider=none) — search degrades gracefully to RRF-only when no
provider is available (e.g. local Ollama 0.32 lacks /api/rerank).
"""

from __future__ import annotations

import abc
import logging
from typing import TYPE_CHECKING, ClassVar

import httpx

if TYPE_CHECKING:
    from earp_server.config import Settings

logger = logging.getLogger(__name__)


class RerankerProvider(abc.ABC):
    """Abstract reranker. Subclass must implement rerank()."""

    name: ClassVar[str] = ""  # provider key, e.g. "ollama"

    @abc.abstractmethod
    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Return relevance scores aligned with documents (higher = more relevant)."""


class OllamaReranker(RerankerProvider):
    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "bge-reranker-v2-m3"):
        self._url = f"{base_url}/api/rerank"
        self._model = model

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self._url,
                json={"model": self._model, "query": query, "documents": documents},
            )
            resp.raise_for_status()
        results = sorted(resp.json()["results"], key=lambda r: r["index"])
        scores = [0.0] * len(documents)
        for r in results:
            scores[r["index"]] = r.get("relevance_score", 0.0)
        return scores


class OpenAICompatReranker(RerankerProvider):
    """OpenAI-compatible /rerank (Cohere/Jina/DashScope style request/response)."""

    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str = "rerank-multilingual-v3.0",
        base_url: str = "https://api.cohere.com/v1",
    ):
        self._api_key = api_key
        self._model = model
        self._url = f"{base_url}/rerank"

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self._url,
                json={"model": self._model, "query": query, "documents": documents},
                headers=headers,
            )
            resp.raise_for_status()
        data = resp.json()
        results = data.get("results") or data.get("data") or []
        scores = [0.0] * len(documents)
        for r in results:
            scores[r["index"]] = r.get("relevance_score", r.get("score", 0.0))
        return scores


# ---------------------------------------------------------------------------
# Factory — module-level singleton (mirrors ext_embedding pattern)
_reranker: RerankerProvider | None = None
_reranker_init = False


def init_reranker_provider(
    provider: str = "none",
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "bge-reranker-v2-m3",
    openai_api_key: str = "",
    openai_model: str = "rerank-multilingual-v3.0",
    openai_base_url: str = "https://api.cohere.com/v1",
) -> None:
    """Initialize the reranker from settings. provider='none' disables (default)."""
    global _reranker, _reranker_init
    p = (provider or "none").lower()
    if p in ("none", "", "disabled"):
        _reranker = None
    elif p == "ollama":
        _reranker = OllamaReranker(ollama_base_url, ollama_model)
    elif p == "openai":
        _reranker = OpenAICompatReranker(openai_api_key, openai_model, openai_base_url)
    else:
        logger.warning("unknown rerank provider %r — disabled", provider)
        _reranker = None
    _reranker_init = True


def get_reranker() -> RerankerProvider | None:
    """Return the configured reranker, or None when disabled. Raises RuntimeError
    when not initialized (startup contract)."""
    if not _reranker_init:
        raise RuntimeError("reranker not initialized — call init_reranker_provider()")
    return _reranker


def init_app(settings: Settings) -> None:
    """Startup hook — initialize reranker from settings (default disabled)."""
    init_reranker_provider(
        provider=getattr(settings, "rerank_provider", "none"),
        ollama_base_url=getattr(settings, "ollama_base_url", "http://localhost:11434"),
        ollama_model=getattr(settings, "ollama_rerank_model", "bge-reranker-v2-m3"),
        openai_api_key=getattr(settings, "openai_api_key", ""),
    )
