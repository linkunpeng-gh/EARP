"""Temporal Retry Policy — 4-parameter retry with STEP_RETRIED events."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from earp_server.infra.eventbus import CloudEvent, EventBus

logger = logging.getLogger(__name__)


@dataclass
class RetryPolicy:
    """Temporal-compatible retry policy (4 standard parameters)."""
    initial_interval: float = 1.0   # seconds before first retry
    backoff_coefficient: float = 2.0  # multiplier for each subsequent retry
    max_attempts: int = 3            # total attempts (1 initial + N-1 retries)
    max_interval: float = 60.0       # cap on retry interval

    def interval_for_attempt(self, attempt: int) -> float:
        """Calculate wait time for the Nth retry attempt (1-indexed after failure)."""
        delay = self.initial_interval * (self.backoff_coefficient ** (attempt - 1))
        return min(delay, self.max_interval)


DEFAULT_RETRY_POLICY = RetryPolicy()


async def execute_with_retry(
    fn: Any,
    *args: Any,
    policy: RetryPolicy | None = None,
    eventbus: EventBus | None = None,
    execution_id: str = "",
    tenant_id: str = "",
    step_id: str = "",
    **kwargs: Any,
) -> Any:
    """Execute fn with retry, publishing STEP_RETRIED events on each retry."""
    if policy is None:
        policy = DEFAULT_RETRY_POLICY
    last_exception = None
    for attempt in range(policy.max_attempts):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt < policy.max_attempts - 1:
                logger.warning("step %s attempt %d/%d failed: %s", step_id, attempt + 1, policy.max_attempts, e)
                if eventbus:
                    eventbus.publish(
                        CloudEvent(
                            type="earp.execution.retried",
                            source="earp-server/orchestrator",
                            tenant_id=tenant_id,
                            data={
                                "execution_id": execution_id,
                                "step_id": step_id,
                                "attempt": attempt + 1,
                                "max_attempts": policy.max_attempts,
                                "error": str(e),
                            },
                        )
                    )
                delay = policy.interval_for_attempt(attempt + 1)
                await asyncio.sleep(delay)
    raise last_exception  # type: ignore[misc]
