"""Incremental indexing — content_hash dedup + old chunk cleanup.

Pattern: langchain-core RecordManager (langchain-earp-mapping section 2.5).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def is_unchanged(engine: AsyncEngine, tenant_id: str, document_id: str, content_hash: str) -> bool:
    """Return True if the document content hasn't changed since last ingest."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT content_hash FROM documents WHERE document_id = :did"),
            {"did": document_id},
        )
        r = row.fetchone()
        return r is not None and r.content_hash == content_hash


async def cleanup_old_chunks(engine: AsyncEngine, tenant_id: str, document_id: str) -> int:
    """Delete old chunks for a document before re-indexing. Returns deleted count."""
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        result = await conn.execute(
            text("DELETE FROM chunks WHERE document_id = :did AND tenant_id = :tid"),
            {"did": document_id, "tid": tenant_id},
        )
        await conn.commit()
        return result.rowcount
