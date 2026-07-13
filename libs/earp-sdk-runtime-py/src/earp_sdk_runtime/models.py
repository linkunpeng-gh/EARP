"""Data models for the Runtime SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CapabilityInfo:
    """Capability metadata from the Discovery API."""

    capability_id: str
    name: str
    description: str = ""
    domain: str = ""
    version: str = ""
    capability_type: str = ""  # "query" | "command"
    tags: list[str] = field(default_factory=list)


@dataclass
class ResolvedCapability:
    """Resolution Engine recommendation result."""

    capability_id: str
    confidence: float = 0.0
    reason: str = ""
    fallback_capabilities: list[str] = field(default_factory=list)


@dataclass
class SearchResponse:
    """Paginated search results."""

    results: list[CapabilityInfo] = field(default_factory=list)
    page: int = 1
    page_size: int = 20
    total: int = 0


@dataclass
class RuntimeEvent:
    """An EventBus event received via subscription."""

    event_id: str = ""
    event_type: str = ""
    source: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    session_id: str | None = None


@dataclass
class SessionStatus:
    """Session status information."""

    session_id: str = ""
    status: str = ""  # "active" | "paused" | "completed" | "archived"
    created_at: str = ""
    expires_at: str | None = None
    execution_count: int = 0
    active_executions: int = 0


@dataclass
class RetryConfig:
    """Retry policy configuration."""

    max_attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0
