"""Vector store behind one interface.

Production: QdrantStore (qdrant-client, URL from QDRANT_URL). If Qdrant is
unreachable, get_vector_store() falls back to InMemoryStore with a warning —
retrieval degrades to "nothing found" instead of failing the request.
Tests use InMemoryStore directly.
"""
from __future__ import annotations

import logging
import math
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("tech-migration-ai.rag")


def collection_name(tech: str, version: Optional[str] = None) -> str:
    """Collection for one tech area, e.g. docs_dotnet_8, docs_java_17."""
    slug = re.sub(r"[^a-z0-9]+", "_", tech.strip().lower()).strip("_") or "unknown"
    if version:
        vslug = re.sub(r"[^a-z0-9]+", "_", version.strip().lower()).strip("_")
        slug = f"{slug}_{vslug}" if vslug else slug
    return f"docs_{slug}"


@dataclass
class ScoredChunk:
    """One retrieval hit."""

    id: str
    text: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectionInfo:
    name: str
    chunks: int


class VectorStore(ABC):
    """Port for the vector database."""

    @abstractmethod
    def upsert(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
        dimension: int,
    ) -> None:
        """Insert or replace points (creates the collection when missing)."""

    @abstractmethod
    def search(
        self,
        collection: str,
        vector: list[float],
        top_k: int = 5,
        filters: Optional[dict[str, str]] = None,
    ) -> list[ScoredChunk]:
        """Nearest-neighbor search with optional exact-match payload filters."""

    @abstractmethod
    def delete_by_filter(self, collection: str, filters: dict[str, str]) -> int:
        """Delete points matching exact-match payload filters. Returns count."""

    @abstractmethod
    def delete_collection(self, collection: str) -> bool:
        """Drop a whole collection. Returns False when it did not exist."""

    @abstractmethod
    def collection_info(self, collection: str) -> Optional[CollectionInfo]:
        """Chunk count, or None when the collection does not exist."""

    @abstractmethod
    def list_collections(self) -> list[str]:
        """Names of all collections."""


class InMemoryStore(VectorStore):
    """Cosine-similarity store. Fallback when Qdrant is down; used by tests."""

    def __init__(self) -> None:
        # collection -> {id: (vector, payload)}
        self._data: dict[str, dict[str, tuple[list[float], dict[str, Any]]]] = {}

    def upsert(self, collection, ids, vectors, payloads, dimension) -> None:
        col = self._data.setdefault(collection, {})
        for pid, vec, payload in zip(ids, vectors, payloads):
            col[pid] = (list(vec), dict(payload))

    def search(self, collection, vector, top_k=5, filters=None) -> list[ScoredChunk]:
        col = self._data.get(collection, {})
        norm_q = math.sqrt(sum(x * x for x in vector)) or 1.0
        hits: list[ScoredChunk] = []
        for pid, (vec, payload) in col.items():
            if filters and any(payload.get(k) != v for k, v in filters.items()):
                continue
            norm_v = math.sqrt(sum(x * x for x in vec)) or 1.0
            score = sum(a * b for a, b in zip(vector, vec)) / (norm_q * norm_v)
            hits.append(
                ScoredChunk(
                    id=pid,
                    text=str(payload.get("text", "")),
                    score=score,
                    payload=payload,
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def delete_by_filter(self, collection: str, filters: dict[str, str]) -> int:
        col = self._data.get(collection, {})
        doomed = [
            pid
            for pid, (_, payload) in col.items()
            if all(payload.get(k) == v for k, v in filters.items())
        ]
        for pid in doomed:
            del col[pid]
        return len(doomed)

    def delete_collection(self, collection: str) -> bool:
        return self._data.pop(collection, None) is not None

    def collection_info(self, collection: str) -> Optional[CollectionInfo]:
        col = self._data.get(collection)
        return CollectionInfo(name=collection, chunks=len(col)) if col is not None else None

    def list_collections(self) -> list[str]:
        return sorted(self._data.keys())


class QdrantStore(VectorStore):
    """Qdrant-backed store. All calls are synchronous (qdrant-client)."""

    def __init__(self, url: Optional[str] = None, timeout: float = 10.0) -> None:
        from qdrant_client import QdrantClient

        self._url = url or os.environ.get("QDRANT_URL", "http://localhost:6333")
        self._client = QdrantClient(url=self._url, timeout=timeout)
        # Fail fast when Qdrant is unreachable so callers can fall back.
        self._client.get_collections()

    def _ensure(self, collection: str, dimension: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        if not self._client.collection_exists(collection):
            self._client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )

    def upsert(self, collection, ids, vectors, payloads, dimension) -> None:
        from qdrant_client.models import PointStruct

        self._ensure(collection, dimension)
        points = [
            PointStruct(id=pid, vector=vec, payload={**pl, "text": pl.get("text", "")})
            for pid, vec, pl in zip(ids, vectors, payloads)
        ]
        self._client.upsert(collection_name=collection, points=points)

    def search(self, collection, vector, top_k=5, filters=None) -> list[ScoredChunk]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        if not self._client.collection_exists(collection):
            return []
        qfilter = None
        if filters:
            qfilter = Filter(
                must=[
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in filters.items()
                ]
            )
        hits = self._client.query_points(
            collection_name=collection,
            query=vector,
            limit=top_k,
            query_filter=qfilter,
            with_payload=True,
        ).points
        return [
            ScoredChunk(
                id=str(h.id),
                text=str((h.payload or {}).get("text", "")),
                score=float(h.score),
                payload=dict(h.payload or {}),
            )
            for h in hits
        ]

    def delete_by_filter(self, collection: str, filters: dict[str, str]) -> int:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        if not self._client.collection_exists(collection):
            return 0
        before = self._client.count(collection_name=collection, exact=True).count
        self._client.delete(
            collection_name=collection,
            points_selector=Filter(
                must=[
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in filters.items()
                ]
            ),
        )
        after = self._client.count(collection_name=collection, exact=True).count
        return max(0, before - after)

    def delete_collection(self, collection: str) -> bool:
        if not self._client.collection_exists(collection):
            return False
        self._client.delete_collection(collection_name=collection)
        return True

    def collection_info(self, collection: str) -> Optional[CollectionInfo]:
        if not self._client.collection_exists(collection):
            return None
        count = self._client.count(collection_name=collection, exact=True).count
        return CollectionInfo(name=collection, chunks=count)

    def list_collections(self) -> list[str]:
        return sorted(c.name for c in self._client.get_collections().collections)


_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """Singleton store: Qdrant when reachable, else in-memory fallback.

    Override in tests via FastAPI dependency_overrides.
    """
    global _store
    if _store is None:
        try:
            _store = QdrantStore()
            logger.info("Connected to Qdrant")
        except Exception as exc:  # Qdrant down -> degrade, don't fail requests
            logger.warning("Qdrant unreachable (%s); using in-memory store", exc)
            _store = InMemoryStore()
    return _store


def reset_vector_store() -> None:
    """Drop the cached singleton (tests only)."""
    global _store
    _store = None
