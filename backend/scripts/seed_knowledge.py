"""Seed the knowledge base with official documentation.

Run on your machine after `docker compose up` (needs network, Ollama with
the embedding model, and Qdrant reachable):

    cd backend && python -m scripts.seed_knowledge

All URLs are official documentation only — the highest-priority RAG source.
Re-running is idempotent: a URL's old chunks are replaced, never duplicated.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag.embeddings import OllamaEmbedder  # noqa: E402
from rag.ingest import IngestItem, ingest_items  # noqa: E402
from rag.vector_store import QdrantStore  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed")

# (url, tech, version, doc_type) — official docs only.
SEED = [
    (
        "https://learn.microsoft.com/en-us/dotnet/csharp/tour-of-csharp/",
        "C#",
        ".NET 8",
        "official",
    ),
    (
        "https://learn.microsoft.com/en-us/ef/core/",
        "EF Core",
        ".NET 8",
        "official",
    ),
    (
        "https://learn.microsoft.com/en-us/aspnet/core/fundamentals/",
        "ASP.NET Core",
        ".NET 8",
        "official",
    ),
    (
        "https://docs.oracle.com/javase/tutorial/",
        "Java",
        "17",
        "official",
    ),
    (
        "https://docs.python.org/3/tutorial/",
        "Python",
        "3",
        "official",
    ),
]


async def main() -> None:
    try:
        store = QdrantStore()
    except Exception as exc:
        logger.error("Qdrant is not reachable: %s", exc)
        logger.error("Start it with `docker compose up qdrant` and retry.")
        raise SystemExit(1)
    embedder = OllamaEmbedder()
    try:
        await embedder.embed(["connectivity check"])
    except Exception as exc:
        logger.error("Ollama embeddings are not reachable: %s", exc)
        logger.error("Run `ollama pull nomic-embed-text` and retry.")
        raise SystemExit(1)

    # Group by (tech, version, doc_type) -> one collection each.
    groups: dict[tuple[str, str, str], list[IngestItem]] = {}
    for url, tech, version, doc_type in SEED:
        groups.setdefault((tech, version, doc_type), []).append(IngestItem(url=url))

    total = 0
    for (tech, version, doc_type), items in groups.items():
        logger.info("Ingesting %d URLs for %s %s ...", len(items), tech, version)
        result = await ingest_items(
            items, tech=tech, version=version, doc_type=doc_type,
            embedder=embedder, store=store,
        )
        for err in result.errors:
            logger.warning("  skipped: %s", err)
        logger.info(
            "  -> %s: %d chunks", result.collection, result.chunks_ingested
        )
        total += result.chunks_ingested
    logger.info("Done: %d chunks across %d collections.", total, len(groups))


if __name__ == "__main__":
    asyncio.run(main())
