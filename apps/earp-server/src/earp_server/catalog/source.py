"""Authoritative-source adapter boundary and safe missing-object policy."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class SourceObject:
    kind: str
    stable_id: str
    version: str
    canonical_input: dict[str, Any]
    content_hash: str
    schema_version: str
    status: str
    data_domain_id: str


class SourceAdapter(Protocol):
    """A source system is authoritative for semantic content, never Catalog."""

    source_system: str

    async def fetch_exact(self, kind: str, stable_id: str, version: str) -> SourceObject: ...

    async def list_since(self, cursor: str | None) -> tuple[list[SourceObject], str | None]: ...

    def source_identity(self, source: SourceObject) -> str:
        """Return the source-owned immutable locator for an exact object version."""
        ...


def webhook_signature_valid(secret: bytes, body: bytes, supplied: str) -> bool:
    """Verify a hex HMAC-SHA256 before accepting a webhook event."""
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


def missing_status(*, prior_status: str, consecutive_misses: int, tombstone: bool) -> str:
    """Never infer deletion from pull absence; retain LKG until authoritative revoke."""
    if tombstone:
        return "inactive"
    if prior_status == "inactive":
        return "inactive"
    del consecutive_misses  # Used for alert escalation, never lifecycle demotion.
    return "suspected_missing"
