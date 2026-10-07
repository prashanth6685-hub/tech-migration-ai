"""Grounding helper: fetch chunks, build the prompt context block.

One shared path for every endpoint that supports grounding (compare/concept,
convert, learn/topic). Returns the context block to append to the task prompt
plus the chunks found. Empty block + no chunks means "answer ungrounded".
"""
from typing import Optional

from domain.schemas import Citation
from rag.embeddings import Embedder
from rag.retriever import RetrievedChunk, retrieve
from rag.vector_store import VectorStore

GROUNDING_BLOCK = """
RETRIEVED DOCUMENTATION — official sources relevant to this request.
Prefer these over your own knowledge for version-specific facts.
{chunks}

RULES:
- For each factual claim you draw from these chunks, add an entry to the
  "sources" array: {{"title": "<chunk title>", "url": "<chunk source URL>"}}.
- Copy titles and URLs EXACTLY as shown above — never invent, shorten, or
  guess URLs.
- If a chunk contradicts your knowledge, trust the chunk and say so.
- If none of the chunks is relevant, leave "sources" empty.
"""


def _format_chunks(chunks: list[RetrievedChunk]) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        url = c.source_url or "(pasted document, no URL)"
        parts.append(
            f"[Chunk {i}] Title: {c.title}\nURL: {url}\n{c.text}"
        )
    return "\n\n---\n\n".join(parts)


async def ground_task(
    query: str,
    tech: str,
    version: Optional[str],
    ground: bool,
    embedder: Embedder,
    store: VectorStore,
    top_k: int = 5,
) -> tuple[str, list[RetrievedChunk]]:
    """Retrieve chunks and build the context block.

    Returns ("", []) when grounding is disabled or nothing was found.
    """
    if not ground:
        return "", []
    chunks = await retrieve(
        query, tech, version, top_k=top_k, embedder=embedder, store=store
    )
    if not chunks:
        return "", []
    return GROUNDING_BLOCK.format(chunks=_format_chunks(chunks)), chunks


def citations_for(chunks: list[RetrievedChunk]) -> list[Citation]:
    """Server-side source list from retrieved chunks (deduped by URL/title)."""
    seen: set[str] = set()
    out: list[Citation] = []
    for c in chunks:
        key = c.source_url or c.title
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(Citation(title=c.title or key, url=c.source_url))
    return out
