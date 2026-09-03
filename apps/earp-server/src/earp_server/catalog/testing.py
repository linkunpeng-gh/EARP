"""Explicit test-only SourceAdapter double for Catalog contract tests."""

from __future__ import annotations

from collections.abc import Iterable

from .source import SourceObject


class MockCatalogSourceAdapter:
    """Deterministic in-memory source; never used by the production composition root."""

    test_only = True

    def __init__(self, source_system: str, objects: Iterable[SourceObject]) -> None:
        source_system = source_system.strip()
        if not source_system:
            raise ValueError("source_system is required")
        self.source_system = source_system
        self._objects = tuple(objects)
        self._by_ref = {(item.kind, item.stable_id, item.version): item for item in self._objects}

    async def fetch_exact(self, kind: str, stable_id: str, version: str) -> SourceObject:
        source = self._by_ref.get((kind, stable_id, version))
        if source is None:
            raise LookupError("mock source object not found")
        return source

    async def list_since(self, cursor: str | None) -> tuple[list[SourceObject], str | None]:
        offset = 0 if cursor is None else int(cursor)
        if offset < 0 or offset > len(self._objects):
            raise ValueError("mock cursor is outside the object page range")
        page = list(self._objects[offset:])
        return page, str(len(self._objects))

    def source_identity(self, source: SourceObject) -> str:
        return f"mock://{self.source_system}/{source.kind}/{source.stable_id}/{source.version}"
