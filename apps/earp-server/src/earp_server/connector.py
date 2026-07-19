"""Capability execution channel. tenacity retry built into execute().

M1 demo: echo adapter passes input through unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

logger = logging.getLogger(__name__)


class ConnectorError(Exception):
    """Raised when a capability adapter fails after exhausting retries."""


class Connector:
    """Execute a capability call with retry. M1 demo: echo adapter only."""

    def __init__(self, eventbus=None) -> None:
        self._bus = eventbus  # optional EventBus for retry events

    @retry(
        retry=retry_if_exception_type(ConnectorError),
        wait=wait_exponential_jitter(),
        stop=stop_after_attempt(3),  # max 3 total attempts (1 initial + 2 retries)
        reraise=True,
    )
    async def execute(self, capability_call: dict[str, Any]) -> dict[str, Any]:
        adapter_type = capability_call.get("adapter_type", "demo.echo")
        logger.debug("connector execute adapter=%s", adapter_type)
        # In M1 the echo adapter simply returns the input as output.
        # Future milestones dispatch to real adapters by type.
        if adapter_type == "demo.echo":
            return {"echo": capability_call.get("input", {})}
        raise ConnectorError(f"unknown adapter: {adapter_type}")

    def _on_retry(self, retry_state) -> None:
        """Publish RETRYING CloudEvent via EventBus when retrying."""
        if self._bus is not None:
            from earp_server.infra.eventbus import CloudEvent
            self._bus.publish(CloudEvent(
                type="earp.connector.retrying",
                source="earp-server/connector",
                tenant_id="",
                data={"attempt": retry_state.attempt_number,
                      "exception": str(retry_state.outcome.exception()) if retry_state.outcome else ""},
            ))
