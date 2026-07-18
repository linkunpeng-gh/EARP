"""Knowledge Base data models — Data Architecture Knowledge domain.

Aligns with Dify core/rag/models/ (Dataset→Document→Segment).
KnowledgeBase → Document → Chunk (1:N:N cascade).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DocumentStatus(str, Enum):
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"


@dataclass
class KnowledgeBase:
    """Top-level container. ≈ Dify Dataset."""
    kb_id: str = ""
    tenant_id: str = ""
    name: str = ""
    description: str = ""
    created_at: str = ""

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, KnowledgeBase):
            return False
        return self.kb_id == other.kb_id

    def __hash__(self) -> int:
        return hash(self.kb_id)


@dataclass
class Document:
    """Uploaded document within a KnowledgeBase. ≈ Dify Document."""
    doc_id: str = ""
    kb_id: str = ""
    tenant_id: str = ""
    title: str = ""
    format: str = "txt"  # txt, pdf, md, html
    status: DocumentStatus = DocumentStatus.PROCESSING
    chunk_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Document):
            return False
        return self.doc_id == other.doc_id

    def __hash__(self) -> int:
        return hash(self.doc_id)


@dataclass
class Chunk:
    """Text segment with embedding vector. ≈ Dify Segment."""
    chunk_id: str = ""
    doc_id: str = ""
    content: str = ""
    embedding: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Chunk):
            return False
        return self.chunk_id == other.chunk_id

    def __hash__(self) -> int:
        return hash(self.chunk_id)


@dataclass(order=True)
class ChunkWithScore:
    """Retrieval result — Chunk with relevance score."""
    score: float = 0.0
    chunk: Chunk = field(default_factory=Chunk, compare=False)

    def __repr__(self) -> str:
        return f"ChunkWithScore(score={self.score:.4f}, chunk_id={self.chunk.chunk_id!r})"
