"""Capability Discovery client — search and browse capabilities via the Registry API.

Aligns with PRD-2026-001 §4.3 interface contract:

    GET /capabilities/search?q={query}&domain={domain}&page={n}&page_size={n}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from earp_sdk_capability.config import load_config

DEFAULT_API_URL = "http://localhost:8080"
DEFAULT_PAGE_SIZE = 20


@dataclass
class SearchResult:
    """A single capability search result."""

    capability_id: str
    name: str
    version: str
    description: str = ""
    confidence: float = 0.0
    domain: str = ""
    tags: list[str] = field(default_factory=list)


@dataclass
class SearchResponse:
    """Paginated search response."""

    results: list[SearchResult] = field(default_factory=list)
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    total: int = 0


class DiscoveryError(Exception):
    """Raised when the Discovery API call fails."""

    def __init__(
        self,
        status_code: int,
        message: str = "",
        *,
        body: Any = None,
    ) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"Discovery API error {status_code}: {message}")


class CapabilityDiscoveryClient:
    """Client for discovering Capabilities via the Registry API.

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

    async def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> SearchResponse:
        """Search Capabilities by semantic query.

        Args:
            query: The search query string.
            domain: Optional domain filter.
            page: Page number (1-indexed).
            page_size: Results per page.

        Returns:
            SearchResponse with matching capabilities.

        Raises:
            DiscoveryError: On HTTP errors.
        """
        params: dict[str, Any] = {"q": query, "page": page, "page_size": page_size}
        if domain:
            params["domain"] = domain

        response = await self._client.get(
            f"{self.api_url}/capabilities/search",
            params=params,
            timeout=30,
        )

        if response.status_code == 200:
            data = response.json()
            results_list = data.get("results", data.get("data", []))
            results = [
                SearchResult(
                    capability_id=r.get("capability_id", ""),
                    name=r.get("name", ""),
                    version=r.get("version", ""),
                    description=r.get("description", ""),
                    confidence=r.get("confidence", 0.0),
                    domain=r.get("domain", ""),
                    tags=r.get("tags", []),
                )
                for r in results_list
            ]
            return SearchResponse(
                results=results,
                page=data.get("page", page),
                page_size=data.get("page_size", page_size),
                total=data.get("total", len(results)),
            )

        try:
            body = response.json()
            message = body.get("message", body.get("error", response.text))
        except Exception:
            body = None
            message = response.text

        raise DiscoveryError(response.status_code, message, body=body)

    async def list_by_domain(
        self,
        domain: str,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> SearchResponse:
        """List all Capabilities in a domain.

        Equivalent to search() with domain filter only.

        Args:
            domain: The domain to list capabilities for.
            page: Page number (1-indexed).
            page_size: Results per page.

        Returns:
            SearchResponse with capabilities in that domain.
        """
        return await self.search("", domain=domain, page=page, page_size=page_size)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
