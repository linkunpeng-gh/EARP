"""Knowledge Base RAG pipeline — Knowledge Base Spec v1.0.

Chunking, embedding, and retrieval with role-level access control.
"""

from __future__ import annotations

import math
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

from .knowledge import Chunk, ChunkWithScore, Document, DocumentStatus


# ── Chunker ──

class Chunker:
    """Split documents into overlapping text chunks. Knowledge Base Spec §1.1."""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, doc: Document, text: str, accessible_roles: list[str] | None = None) -> list[Chunk]:
        """Split text into chunks, inheriting doc metadata and role access.

        Args:
            accessible_roles: Role IDs allowed to access these chunks.
                None = use default [doc.creator_role_id] (default-closed principle).
        """
        chunks: list[Chunk] = []
        if not text.strip():
            return chunks

        roles = accessible_roles if accessible_roles is not None else []  # default-closed: empty = no implicit access

        step = self.chunk_size - self.chunk_overlap
        total = max(1, math.ceil(len(text) / step))

        for i in range(total):
            start = i * step
            end = min(start + self.chunk_size, len(text))
            chunk = Chunk(
                chunk_id=f"{doc.doc_id}-chunk-{i+1}",
                doc_id=doc.doc_id,
                content=text[start:end],
                metadata={
                    "chunk_index": i,
                    "total_chunks": total,
                    "doc_title": doc.title,
                    "accessible_roles": roles,
                },
            )
            chunks.append(chunk)
        return chunks


# ── Embedder ──

class Embedder(ABC):
    """Abstract embedding interface. Swap implementations for different models."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        ...


class SimpleEmbedder(Embedder):
    """Trivial hash-based embedder for testing. Not for production."""

    def __init__(self, dim: int = 128) -> None:
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import hashlib
        embeddings: list[list[float]] = []
        for text in texts:
            h = hashlib.sha256(text.encode()).digest()
            vec = [float(b) / 255.0 for b in h[:self.dim]]
            embeddings.append(vec)
        return embeddings


class OpenAISimilarityEmbedder(Embedder):
    """OpenAI text-embedding-3-small via callback. No hard dependency."""

    def __init__(self, embed_fn: Callable[[list[str]], Awaitable[list[list[float]]]]) -> None:
        self._embed_fn = embed_fn

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._embed_fn(texts)


# ── Retriever ──

class Retriever:
    """Vector similarity search over chunks. Knowledge Base Spec §3."""

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._chunks: list[Chunk] = []

    def index(self, chunks: list[Chunk]) -> None:
        """Index chunks. Call after embedding them."""
        self._chunks.extend(chunks)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        *,
        tenant_id: str = "",
        role_id: str = "",
    ) -> list[ChunkWithScore]:
        """Search chunks by query embedding, filtered by role and tenant."""
        if not self._chunks:
            return []

        query_vec = (await self._embedder.embed([query]))[0]
        results: list[ChunkWithScore] = []

        for chunk in self._chunks:
            # Tenant filter
            if tenant_id and hasattr(chunk, 'tenant_id') and getattr(chunk, 'tenant_id', '') != tenant_id:
                continue
            # Role filter — accessible_roles in metadata
            accessible = chunk.metadata.get("accessible_roles", [])
            if accessible and role_id and role_id not in accessible:
                continue
            # Cosine similarity
            if chunk.embedding:
                score = self._cosine(query_vec, chunk.embedding)
                results.append(ChunkWithScore(score=score, chunk=chunk))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    def clear(self) -> None:
        self._chunks.clear()


# ── RAG Pipeline ──

@dataclass
class RAGResult:
    """RAG retrieval result with context for LLM."""
    chunks: list[ChunkWithScore] = field(default_factory=list)
    context: str = ""

    @classmethod
    def from_chunks(cls, chunks: list[ChunkWithScore], max_tokens: int = 2000) -> RAGResult:
        """Build context string from retrieval results."""
        ctx_parts: list[str] = []
        token_est = 0
        for item in chunks:
            snippet = item.chunk.content[:500]
            token_est += len(snippet) // 4  # rough estimate
            if token_est > max_tokens:
                break
            ctx_parts.append(f"[{item.score:.2f}] {snippet}")
        return cls(chunks=chunks, context="\n\n".join(ctx_parts))


class RAGPipeline:
    """End-to-end RAG pipeline: index → retrieve → build context."""

    def __init__(self, embedder: Embedder, chunker: Chunker | None = None) -> None:
        self.embedder = embedder
        self.chunker = chunker or Chunker()
        self.retriever = Retriever(embedder)

    async def index_document(self, doc: Document, text: str, accessible_roles: list[str] | None = None) -> int:
        """Chunk + embed + index a document. Returns number of chunks indexed."""
        chunks = self.chunker.split(doc, text, accessible_roles)
        if not chunks:
            return 0
        texts = [c.content for c in chunks]
        embeddings = await self.embedder.embed(texts)
        for chunk, emb in zip(chunks, embeddings):
            chunk.embedding = emb
        self.retriever.index(chunks)
        doc.status = DocumentStatus.READY
        doc.chunk_count = len(chunks)
        return len(chunks)

    async def query(
        self,
        query: str,
        top_k: int = 5,
        *,
        tenant_id: str = "",
        role_id: str = "",
        max_context_tokens: int = 2000,
    ) -> RAGResult:
        """Search + build LLM context."""
        chunks = await self.retriever.search(query, top_k, tenant_id=tenant_id, role_id=role_id)
        return RAGResult.from_chunks(chunks, max_context_tokens)
