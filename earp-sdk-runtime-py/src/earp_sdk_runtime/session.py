"""Session — EARP Session lifecycle management."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx

from earp_sdk_runtime.events import EventSubscriber
from earp_sdk_runtime.invoker import CapabilityInvoker
from earp_sdk_runtime.models import SessionStatus


logger = logging.getLogger(__name__)


class Session:
    """An EARP Session — the outer container for multiple Executions.

    Aligns with L2-01-RUNTIME §6.3 Session contract.
    """

    def __init__(
        self,
        session_id: str,
        tenant_id: str,
        user_id: str,
        status: str = "active",
        *,
        _client: httpx.AsyncClient,
        _endpoint: str,
    ) -> None:
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.status = status
        self.created_at = datetime.utcnow()

        self.capabilities = CapabilityInvoker(
            session_id=session_id,
            client=_client,
            endpoint=_endpoint,
        )
        self.events = EventSubscriber(
            session_id=session_id,
            client=_client,
            endpoint=_endpoint,
        )

        self._client = _client
        self._endpoint = _endpoint

    async def pause(self) -> None:
        """⚠️ Reserved. Not implemented in v1."""
        raise NotImplementedError("Session.pause() is reserved for v1.1")

    async def resume(self) -> None:
        """⚠️ Reserved. Not implemented in v1."""
        raise NotImplementedError("Session.resume() is reserved for v1.1")

    async def close(self) -> None:
        """Close the Session."""
        if self.status == "completed":
            return
        try:
            await self._client.patch(
                f"{self._endpoint}/v1/sessions/{self.session_id}",
                json={"status": "completed"},
                timeout=30,
            )
        except httpx.HTTPError as e:
            logger.warning("Session.close() failed to notify server: %s", e)
        self.status = "completed"

    async def status_info(self) -> SessionStatus:
        """Get current Session status from the Runtime."""
        response = await self._client.get(
            f"{self._endpoint}/v1/sessions/{self.session_id}",
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return SessionStatus(
            session_id=data["session_id"],
            status=data.get("status", self.status),
            created_at=data.get("created_at", ""),
            expires_at=data.get("expires_at"),
            execution_count=data.get("execution_count", 0),
            active_executions=data.get("active_executions", 0),
        )
