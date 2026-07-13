"""Registry HTTP client — registers, activates, and manages Capabilities.

Communicates with the Capability Center's Registry REST API.
Uses the Packager to convert Python classes to the three-layer JSON format.

Usage:

    from earp_sdk_capability.registration.client import CapabilityRegistryClient
    from my_caps import QueryEquipmentAlarm

    client = CapabilityRegistryClient()
    result = await client.register(QueryEquipmentAlarm)
    # result.capability_id == "query_equipment_alarm"
    # result.status == "draft"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from earp_sdk_capability.base import Capability
from earp_sdk_capability.config import load_config
from earp_sdk_capability.registration.packager import packager

DEFAULT_API_URL = "http://localhost:8080"


@dataclass
class RegistryResult:
    """Result of a registration or activation call."""

    capability_id: str
    version: str
    status: str


class RegistryError(Exception):
    """Raised when a Registry API call fails."""

    def __init__(
        self,
        status_code: int,
        message: str = "",
        *,
        body: Any = None,
    ) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Registry API error {status_code}: {message}")


class CapabilityRegistryClient:
    """Client for the Capability Center Registry API.

    Args:
        api_url: The base URL of the Registry service.
                 Defaults to config or http://localhost:8080.
        client: An optional httpx.AsyncClient for custom transport/headers.
    """

    def __init__(
        self,
        api_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if api_url is None:
            config = load_config()
            api_url = config.earp.registry.api_url
        self.api_url = api_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            headers={"User-Agent": "earp-sdk-capability/0.1.0.dev0"},
        )

    async def prepare(self, cap_cls: type[Capability]) -> dict[str, Any]:
        """Convert a Capability class to the three-layer JSON package.

        This is a local operation — no network call.

        Args:
            cap_cls: The Capability class to package.

        Returns:
            The three-layer JSON dict ready for registration.
        """
        return packager.pack(cap_cls)

    async def register(
        self,
        cap_cls: type[Capability],
    ) -> RegistryResult:
        """Register a Capability (POST /capabilities).

        The package is sent as draft status.

        Args:
            cap_cls: The Capability class to register.

        Returns:
            RegistryResult with capability_id, version, and status.

        Raises:
            RegistryError: On HTTP errors.
            ValueError: If the Capability class is incomplete.
        """
        package = await self.prepare(cap_cls)
        return await self._register_package(package)

    async def _register_package(self, package: dict[str, Any]) -> RegistryResult:
        """Internal: send a pre-built package to the Registry API."""
        response = await self._client.post(
            f"{self.api_url}/capabilities",
            json=package,
            timeout=30,
        )

        if response.status_code == 201:
            data = response.json()
            return RegistryResult(
                capability_id=data["capability_id"],
                version=data["version"],
                status=data.get("status", "draft"),
            )

        # Try to extract error details
        try:
            body = response.json()
            message = body.get("message", body.get("error", response.text))
        except Exception:
            body = None
            message = response.text

        raise RegistryError(response.status_code, message, body=body)

    async def activate(self, capability_id: str) -> RegistryResult:
        """Activate a draft Capability (PATCH /capabilities/{id}).

        Args:
            capability_id: The capability_id to activate.

        Returns:
            RegistryResult with the updated status.

        Raises:
            RegistryError: On HTTP errors.
        """
        response = await self._client.patch(
            f"{self.api_url}/capabilities/{capability_id}",
            json={"status": "active"},
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            return RegistryResult(
                capability_id=data["capability_id"],
                version=data["version"],
                status=data.get("status", "active"),
            )

        try:
            body = response.json()
            message = body.get("message", body.get("error", response.text))
        except Exception:
            body = None
            message = response.text

        raise RegistryError(response.status_code, message, body=body)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
