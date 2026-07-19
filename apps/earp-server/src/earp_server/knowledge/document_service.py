"""Document ingestion — create document row, trigger chunk pipeline."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def create_document(
    engine: AsyncEngine,
    tenant_id: str,
    knowledge_base_id: str,
    content: str,
    title: str = "",
) -> dict:
    document_id = f"doc-{uuid.uuid4().hex[:12]}"
    content_hash = hashlib.md5(content.encode()).hexdigest()
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        await conn.execute(
            text(
                "INSERT INTO documents (document_id, tenant_id, knowledge_base_id, title, content, content_hash) "
                "VALUES (:did, :tid, :kid, :title, :content, :chash)"
            ),
            {"did": document_id, "tid": tenant_id, "kid": knowledge_base_id, "title": title,
             "content": content, "chash": content_hash},
        )
        await conn.commit()
    return {"document_id": document_id, "content_hash": content_hash}


async def get_document(engine: AsyncEngine, document_id: str, tenant_id: str) -> dict | None:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET LOCAL earp.tenant_id = '{tenant_id}'"))
        row = await conn.execute(
            text("SELECT document_id, title, content, content_hash FROM documents WHERE document_id = :did"),
            {"did": document_id},
        )
        r = row.fetchone()
        return dict(r._mapping) if r else None
