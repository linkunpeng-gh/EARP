"""Langfuse LLM observability tracer — M15.

Wraps LLMConnector and embedding calls with Langfuse tracing
for token usage, latency, and error tracking.

When langfuse keys are not configured (empty), tracing is silently disabled.
"""

from __future__ import annotations

import logging
from typing import Any

from earp_server.config import Settings

logger = logging.getLogger(__name__)

# Langfuse SDK is optional — import fails gracefully if not installed.
_has_langfuse = False
try:
    from langfuse import Langfuse as _LangfuseClient  # type: ignore[assignment]

    _has_langfuse = True
except ImportError:
    _LangfuseClient = None  # type: ignore[assignment]


class LangfuseTracer:
    """Langfuse tracing wrapper. No-op when keys are not configured."""

    def __init__(self, settings: Settings) -> None:
        self._enabled = bool(_has_langfuse and settings.langfuse_public_key and settings.langfuse_secret_key)
        if self._enabled and _LangfuseClient is not None:
            self._client = _LangfuseClient(  # type: ignore[misc]
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            logger.info("LangfuseTracer: enabled, host=%s", settings.langfuse_host)
        else:
            self._client = None
            logger.info("LangfuseTracer: disabled (no keys or SDK not installed)")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def trace_llm(
        self,
        name: str,
        model: str,
        prompt: str,
        *,
        output: str | None = None,
        error: str | None = None,
        latency_ms: int = 0,
        usage: dict[str, int] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an LLM call trace."""
        if not self._enabled or not self._client:
            return
        try:
            trace = self._client.trace(name=name, metadata=metadata)  # type: ignore[union-attr]
            trace.generation(  # type: ignore[union-attr]
                name=f"{name}-gen",
                model=model,
                input=prompt,
                output=output,
                usage=usage,
                metadata={"error": error, "latency_ms": latency_ms} if error else {"latency_ms": latency_ms},
            )
        except Exception:
            logger.debug("LangfuseTracer: trace_llm failed", exc_info=True)

    def trace_embedding(
        self,
        model: str,
        input_texts: list[str],
        *,
        latency_ms: int = 0,
        error: str | None = None,
    ) -> None:
        """Record an embedding call trace."""
        if not self._enabled or not self._client:
            return
        try:
            trace = self._client.trace(name="embedding")  # type: ignore[union-attr]
            trace.generation(  # type: ignore[union-attr]
                name="embedding-gen",
                model=model,
                input=input_texts,
                usage={"input_tokens": sum(len(t.split()) for t in input_texts)},
                metadata={"error": error, "latency_ms": latency_ms, "batch_size": len(input_texts)}
                if error
                else {"latency_ms": latency_ms, "batch_size": len(input_texts)},
            )
        except Exception:
            logger.debug("LangfuseTracer: trace_embedding failed", exc_info=True)

    def flush(self) -> None:
        """Flush pending traces. Call before shutdown."""
        if self._enabled and self._client:
            try:
                self._client.flush()
            except Exception:
                pass
