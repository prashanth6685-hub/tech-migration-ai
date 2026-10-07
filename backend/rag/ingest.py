"""Ingestion pipeline: fetch -> clean -> chunk -> embed -> upsert.

Inputs are URL fetches and/or raw markdown. Chunking is markdown-aware:
splits on headers and paragraphs, never splits fenced code blocks, ~2000
chars per chunk with ~15% overlap. Re-ingesting the same URL replaces its
chunks instead of duplicating them (idempotent via source_url + content hash).
"""
from __future__ import annotations

import hashlib
import html as html_lib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

from rag.embeddings import Embedder
from rag.vector_store import VectorStore, collection_name

logger = logging.getLogger("tech-migration-ai.rag")

MAX_CHUNK_CHARS = 2000  # ~500 tokens
OVERLAP_CHARS = 300  # ~15% overlap
MAX_URLS_PER_REQUEST = 20
MAX_MARKDOWN_CHARS = 200_000
FETCH_TIMEOUT = 30.0


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# HTML -> text
# ---------------------------------------------------------------------------


def html_to_text(html: str) -> str:
    """Extract main content. trafilatura first; simple tag-stripper fallback."""
    try:
        import trafilatura

        extracted = trafilatura.extract(
            html, include_links=False, include_images=False, favor_recall=True
        )
        if extracted and len(extracted.strip()) > 200:
            return extracted.strip()
    except Exception as exc:  # lib missing or parse failed -> fallback
        logger.debug("trafilatura failed, using fallback cleaner: %s", exc)
    # Fallback: strip scripts/styles/nav, then tags.
    text = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def fetch_url(url: str) -> str:
    """Fetch a URL and return cleaned text. Raises on failure."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(FETCH_TIMEOUT),
        headers={"User-Agent": "tech-migration-ai/1.0 (doc-ingestion)"},
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    body = resp.text
    if "html" in content_type or body.lstrip().lower().startswith("<!doctype") or body.lstrip().startswith("<html"):
        return html_to_text(body)
    return body.strip()


# ---------------------------------------------------------------------------
# Markdown-aware chunking (never splits fenced code blocks)
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")
_HEADER_RE = re.compile(r"^#{1,6}\s")


def _split_segments(md: str) -> list[str]:
    """Split markdown into segments: headers, fenced code blocks (kept whole),
    and paragraphs. A fenced block is never split across segments."""
    segments: list[str] = []
    buf: list[str] = []
    in_fence = False
    fence_mark = ""

    def flush() -> None:
        text = "\n".join(buf).strip()
        if text:
            segments.append(text)
        buf.clear()

    for line in md.splitlines():
        fence = _FENCE_RE.match(line.strip())
        if fence:
            mark = fence.group(1)[0]
            if not in_fence:
                flush()
                in_fence = True
                fence_mark = mark
                buf.append(line)
            elif line.strip().startswith(fence_mark * 3):
                buf.append(line)
                flush()  # code block stays one segment
                in_fence = False
            else:
                buf.append(line)
            continue
        if in_fence:
            buf.append(line)
            continue
        if _HEADER_RE.match(line.strip()):
            flush()
            segments.append(line.strip())
            continue
        if not line.strip():
            flush()
            continue
        buf.append(line)
    flush()
    return segments


def _split_long_segment(segment: str) -> list[str]:
    """Split an oversized segment by lines (last resort, e.g. huge code)."""
    lines = segment.splitlines()
    parts: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for line in lines:
        if cur_len + len(line) + 1 > MAX_CHUNK_CHARS and cur:
            parts.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
    if cur:
        parts.append("\n".join(cur))
    return parts


def chunk_markdown(md: str) -> list[str]:
    """Pack segments into ~2000-char chunks with ~300-char overlap."""
    segments: list[str] = []
    for seg in _split_segments(md):
        segments.append(seg) if len(seg) <= MAX_CHUNK_CHARS else segments.extend(
            _split_long_segment(seg)
        )

    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for seg in segments:
        if cur and cur_len + len(seg) + 2 > MAX_CHUNK_CHARS:
            chunks.append("\n\n".join(cur))
            # Overlap: carry trailing segments totalling <= OVERLAP_CHARS.
            overlap: list[str] = []
            overlap_len = 0
            for s in reversed(cur):
                if overlap_len + len(s) > OVERLAP_CHARS:
                    break
                overlap.insert(0, s)
                overlap_len += len(s) + 2
            cur, cur_len = overlap, overlap_len
        cur.append(seg)
        cur_len += len(seg) + 2
    if cur:
        chunks.append("\n\n".join(cur))
    return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


@dataclass
class IngestItem:
    url: Optional[str] = None
    title: Optional[str] = None
    markdown: Optional[str] = None


@dataclass
class IngestResult:
    collection: str
    chunks_ingested: int
    items: int
    errors: list[str] = field(default_factory=list)


async def ingest_items(
    items: list[IngestItem],
    tech: str,
    version: Optional[str],
    doc_type: str,
    embedder: Embedder,
    store: VectorStore,
) -> IngestResult:
    """Run the full pipeline for a batch of items into one collection."""
    coll = collection_name(tech, version)
    fetched_at = datetime.now(timezone.utc).isoformat()
    errors: list[str] = []
    all_chunks: list[tuple[str, dict]] = []  # (text, payload)

    for item in items:
        try:
            if item.url:
                title = item.url
                text = await fetch_url(item.url)
                if len(text.strip()) < 100:
                    raise ValueError("page yielded almost no text content")
                # Dedupe: drop this URL's old chunks before inserting fresh ones.
                store.delete_by_filter(coll, {"source_url": item.url})
                source_url = item.url
            elif item.markdown:
                title = item.title or "pasted document"
                text = item.markdown
                source_url = ""
                # Dedupe pasted docs by title + content hash.
                h = content_hash(text)
                store.delete_by_filter(coll, {"title": title, "content_hash": h})
            else:
                raise ValueError("item needs url or markdown")
        except Exception as exc:
            errors.append(f"{item.url or item.title or 'item'}: {exc}")
            continue

        for i, chunk in enumerate(chunk_markdown(text)):
            payload = {
                "text": chunk,
                "title": title,
                "source_url": source_url,
                "tech": tech,
                "version": version or "",
                "doc_type": doc_type,
                "fetched_at": fetched_at,
                "content_hash": content_hash(chunk),
                "chunk_index": i,
            }
            all_chunks.append((chunk, payload))

    if not all_chunks:
        return IngestResult(collection=coll, chunks_ingested=0, items=0, errors=errors)

    texts = [c for c, _ in all_chunks]
    vectors = await embedder.embed(texts)
    ids = [
        content_hash(f"{p['source_url'] or p['title']}:{p['chunk_index']}:{p['content_hash']}")
        for _, p in all_chunks
    ]
    store.upsert(
        coll,
        ids=ids,
        vectors=vectors,
        payloads=[p for _, p in all_chunks],
        dimension=len(vectors[0]),
    )
    return IngestResult(
        collection=coll,
        chunks_ingested=len(all_chunks),
        items=len(items) - len(errors),
        errors=errors,
    )
