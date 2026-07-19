"""Saga compensation — M5 minimal: register compensate callbacks, rollback on failure."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# compensate callback: (step_context) -> None
CompensateFn = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class SagaCompensation:
    """Minimal saga: register compensate callbacks, execute in reverse on failure."""

    def __init__(self) -> None:
        self._compensations: list[tuple[str, CompensateFn, dict[str, Any]]] = []

    def register(self, step_id: str, compensate: CompensateFn, context: dict[str, Any] | None = None) -> None:
        self._compensations.append((step_id, compensate, context or {}))

    async def rollback(self) -> None:
        """Execute all registered compensations in reverse order (LIFO)."""
        for step_id, compensate, context in reversed(self._compensations):
            try:
                logger.info("compensating step %s", step_id)
                await compensate(context)
            except Exception:
                logger.exception("compensation failed for step %s", step_id)
        self._compensations.clear()

    @property
    def count(self) -> int:
        return len(self._compensations)
