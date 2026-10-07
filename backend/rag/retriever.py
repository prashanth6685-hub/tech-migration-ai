"""Retrieval: embed the query, vector-search the tech's collection.

Version filtering is mandatory: a query about .NET 8 never silently pulls
.NET Framework 4.8 guidance — the collection is per tech+version, with a
tech-only fallback collection only when the versioned one is empty.

Fail-closed: any embedding/store error returns [] and the caller answers
from model knowledge with an "ungrounded" marker — a request never fails
because the knowledge base is unavailable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from rag.embeddings import Embedder, get_embedder
from rag.vector_store import VectorStore, collection_name, get_vector_store

logger = logging.getLogger("tech-migration-ai.rag")


@dataclass
class RetrievedChunk:
    text: str
    title: str
    source_url: str
    score: float
    payload: dict[str, Any]


async def retrieve(
    query: str,
    tech: str,
    version: Optional[str] = None,
    top_k: int = 5,
    embedder: Optional[Embedder] = None,
    store: Optional[VectorStore] = None,
) -> list[RetrievedChunk]:
    """Return the top chunks for a query, or [] when nothing is available."""
    if not query.strip():
        return []
    embedder = embedder or get_embedder()
    store = store or get_vector_store()
    try:
        collections = [collection_name(tech, version)]
        if version:
            collections.append(collection_name(tech, None))
        query_vec = (await embedder.embed([query]))[0]
        hits: list[RetrievedChunk] = []
        for coll in collections:
            for hit in store.search(coll, query_vec, top_k=top_k):
                hits.append(
                    RetrievedChunk(
                        text=hit.text,
                        title=str(hit.payload.get("title", "")),
                        source_url=str(hit.payload.get("source_url", "")),
                        score=hit.score,
                        payload=hit.payload,
                    )
                )
            if hits:
                break  # versioned collection wins when it has anything
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]
    except Exception as exc:
        logger.warning("Retrieval failed (%s); answering ungrounded", exc)
        return []
