"""Phase 5 RAG tests. No network, no Ollama, no Qdrant — everything faked.

HashEmbedder + InMemoryStore stand in for the real pipeline; the LLM is the
usual dependency-override fake. URL fetching is never exercised here
(ingest_items is fed markdown directly).
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from llm.provider import AIProvider, get_provider
from main import app
from rag.embeddings import HashEmbedder, get_embedder
from rag.grounding import citations_for, ground_task
from rag.ingest import (
    MAX_CHUNK_CHARS,
    OVERLAP_CHARS,
    IngestItem,
    chunk_markdown,
    html_to_text,
    ingest_items,
)
from rag.retriever import retrieve
from rag.vector_store import InMemoryStore, collection_name, get_vector_store


class _JsonProvider(AIProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, responses):
        self._responses = list(responses)

    async def chat_stream(self, messages, system=None):
        yield self._responses[0]

    async def ping(self):
        return True


def _fresh_store():
    return InMemoryStore()


def _client_with(provider=None, embedder=None, store=None):
    if provider is not None:
        app.dependency_overrides[get_provider] = lambda: provider
    else:
        app.dependency_overrides.pop(get_provider, None)
    if embedder is not None:
        app.dependency_overrides[get_embedder] = lambda: embedder
    else:
        app.dependency_overrides.pop(get_embedder, None)
    if store is not None:
        app.dependency_overrides[get_vector_store] = lambda: store
    else:
        app.dependency_overrides.pop(get_vector_store, None)
    return TestClient(app)


def _seed(store, embedder, texts, tech="C#", version=".NET 8"):
    items = [
        IngestItem(title=f"Doc {i}", markdown=text) for i, text in enumerate(texts)
    ]
    return asyncio.run(
        ingest_items(items, tech=tech, version=version, doc_type="official",
                     embedder=embedder, store=store)
    )


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------


def test_hash_embedder_is_deterministic_and_normalized():
    e = HashEmbedder(dimension=32)
    a, b = asyncio.run(e.embed(["hello world", "hello world"]))
    assert a == b
    assert e.dimension == 32
    norm = sum(x * x for x in a) ** 0.5
    assert abs(norm - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Collection naming
# ---------------------------------------------------------------------------


def test_collection_name_slugs():
    assert collection_name("C#", ".NET 8") == "docs_c_net_8"
    assert collection_name("Java", "17") == "docs_java_17"
    assert collection_name("ASP.NET Core") == "docs_asp_net_core"


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def test_chunk_markdown_keeps_code_blocks_whole():
    code = "```csharp\n" + "\n".join(f"var x{i} = {i};" for i in range(120)) + "\n```"
    md = "# Title\n\nSome intro paragraph.\n\n" + code + "\n\n## Next\n\nMore text."
    chunks = chunk_markdown(md)
    assert chunks, "expected at least one chunk"
    joined = "\n".join(chunks)
    assert "var x0 = 0;" in joined and "var x119 = 119;" in joined
    # The fence markers must not be split across a chunk boundary mid-block:
    for chunk in chunks:
        assert chunk.count("```") % 2 == 0, "fenced block split across chunks"


def test_chunk_markdown_splits_on_headers_and_overlaps():
    md = "\n\n".join(
        f"## Section {i}\n\n" + ("Paragraph %d lorem ipsum dolor sit amet. " % i) * 24
        for i in range(10)
    )
    chunks = chunk_markdown(md)
    assert len(chunks) > 1
    joined = "\n".join(chunks)
    for i in range(10):
        assert f"Section {i}" in joined
    # No chunk exceeds the size budget by much (overlap excluded).
    assert all(len(c) <= MAX_CHUNK_CHARS + OVERLAP_CHARS + 200 for c in chunks)


def test_html_to_text_fallback_strips_tags():
    html = (
        "<html><head><style>body{color:red}</style></head>"
        "<body><nav>menu</nav><h1>Hello</h1><p>World</p>"
        "<script>alert(1)</script></body></html>"
    )
    text = html_to_text(html)
    assert "Hello" in text and "World" in text
    assert "alert" not in text and "color:red" not in text


# ---------------------------------------------------------------------------
# Ingestion + dedupe
# ---------------------------------------------------------------------------


def test_ingest_markdown_and_dedupe_on_reingest():
    store, embedder = _fresh_store(), HashEmbedder()
    texts = ["# LINQ\n\nLanguage Integrated Query filters collections."]
    first = _seed(store, embedder, texts)
    assert first.chunks_ingested > 0
    info = store.collection_info("docs_c_net_8")
    assert info is not None and info.chunks == first.chunks_ingested
    second = _seed(store, embedder, texts)  # same docs again
    info2 = store.collection_info("docs_c_net_8")
    assert info2.chunks == info.chunks, "re-ingest must replace, not duplicate"


def test_ingest_empty_markdown_is_an_error_item():
    store, embedder = _fresh_store(), HashEmbedder()
    result = asyncio.run(
        ingest_items(
            [IngestItem(title="Empty", markdown="   ")],
            tech="C#", version=None, doc_type="official",
            embedder=embedder, store=store,
        )
    )
    assert result.chunks_ingested == 0


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def test_retrieve_returns_relevant_chunk():
    store, embedder = _fresh_store(), HashEmbedder()
    _seed(store, embedder, [
        "# LINQ\n\nWhere filters a sequence. ToList materializes the query.",
        "# Pizza\n\nDough, tomato sauce, mozzarella cheese, basil.",
    ])
    hits = asyncio.run(retrieve("How do I filter a sequence with Where?",
                                "C#", ".NET 8", embedder=embedder, store=store))
    assert hits
    assert "Where" in hits[0].text


def test_retrieve_empty_store_returns_empty():
    store, embedder = _fresh_store(), HashEmbedder()
    hits = asyncio.run(retrieve("anything", "C#", ".NET 8",
                                embedder=embedder, store=store))
    assert hits == []


def test_retrieve_falls_back_to_tech_only_collection():
    store, embedder = _fresh_store(), HashEmbedder()
    _seed(store, embedder, ["# LINQ\n\nWhere filters."], tech="C#", version=None)
    hits = asyncio.run(retrieve("filter with Where", "C#", ".NET 8",
                                embedder=embedder, store=store))
    assert hits and "Where" in hits[0].text


# ---------------------------------------------------------------------------
# Grounding helper
# ---------------------------------------------------------------------------


def test_ground_task_disabled_returns_empty():
    store, embedder = _fresh_store(), HashEmbedder()
    block, chunks = asyncio.run(
        ground_task("q", "C#", ".NET 8", ground=False, embedder=embedder, store=store)
    )
    assert block == "" and chunks == []


def test_citations_dedupe():
    from rag.retriever import RetrievedChunk

    chunks = [
        RetrievedChunk(text="a", title="T", source_url="http://x", score=1.0, payload={}),
        RetrievedChunk(text="b", title="T", source_url="http://x", score=0.9, payload={}),
    ]
    cites = citations_for(chunks)
    assert len(cites) == 1 and cites[0].url == "http://x"


# ---------------------------------------------------------------------------
# Knowledge API
# ---------------------------------------------------------------------------


def test_ingest_endpoint_and_collections_roundtrip():
    store, embedder = _fresh_store(), HashEmbedder()
    client = _client_with(embedder=embedder, store=store)
    resp = client.post("/api/knowledge/ingest", json={
        "items": [{"title": "LINQ doc", "markdown": "# LINQ\n\nWhere filters sequences."}],
        "tech": "C#",
        "version": ".NET 8",
        "doc_type": "official",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["collection"] == "docs_c_net_8"
    assert body["chunks_ingested"] > 0

    colls = client.get("/api/knowledge/collections").json()
    assert any(c["name"] == "docs_c_net_8" and c["chunks"] > 0 for c in colls)


def test_ingest_endpoint_rejects_bad_items():
    client = _client_with(embedder=HashEmbedder(), store=_fresh_store())
    resp = client.post("/api/knowledge/ingest", json={"items": [], "tech": "C#"})
    assert resp.status_code == 422
    resp = client.post("/api/knowledge/ingest",
                       json={"items": [{"title": "No body"}], "tech": "C#"})
    assert resp.status_code == 422


def test_delete_collection_guards():
    store = _fresh_store()
    client = _client_with(store=store)
    resp = client.delete("/api/knowledge/collections/notdocs")
    assert resp.status_code == 400
    resp = client.delete("/api/knowledge/collections/docs_missing")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Grounded vs ungrounded endpoint behavior
# ---------------------------------------------------------------------------

CONCEPT_JSON = {
    "source_technology": "Java (17)",
    "target_technology": "C# (.NET 8)",
    "concept": "CompletableFuture",
    "equivalence": "conceptual",
    "source_implementation": "CompletableFuture.supplyAsync(() -> 1);",
    "target_implementation": "await Task.Run(() => 1);",
    "key_difference": "Task underpins async/await.",
    "target_specific_improvement": "",
    "common_migration_problem": "",
    "recommended_approach": "Prefer async/await over ContinueWith.",
}

_CONCEPT_BODY = {
    "source_tech": "Java",
    "source_version": "17",
    "target_tech": "C#",
    "target_version": ".NET 8",
    "concept": "CompletableFuture",
}


def test_concept_grounded_when_docs_exist():
    store, embedder = _fresh_store(), HashEmbedder()
    _seed(store, embedder, [
        "# Task\n\nTask.Run queues work to the thread pool. await unwraps results.",
    ])
    provider = _JsonProvider([json.dumps(CONCEPT_JSON)])
    client = _client_with(provider=provider, embedder=embedder, store=store)
    resp = client.post("/api/compare/concept", json=_CONCEPT_BODY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["grounded"] is True
    assert body["sources"], "expected server-filled citations"
    assert body["sources"][0]["title"] == "Doc 0"


def test_concept_ungrounded_when_knowledge_base_empty():
    provider = _JsonProvider([json.dumps(CONCEPT_JSON)])
    client = _client_with(provider=provider, embedder=HashEmbedder(),
                          store=_fresh_store())
    resp = client.post("/api/compare/concept", json=_CONCEPT_BODY)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["grounded"] is False
    assert body["sources"] == []


def test_concept_ground_false_skips_retrieval():
    store, embedder = _fresh_store(), HashEmbedder()
    _seed(store, embedder, ["# Task\n\nTask.Run queues work."])
    provider = _JsonProvider([json.dumps(CONCEPT_JSON)])
    client = _client_with(provider=provider, embedder=embedder, store=store)
    resp = client.post("/api/compare/concept",
                       json={**_CONCEPT_BODY, "ground": False})
    assert resp.status_code == 200
    assert resp.json()["grounded"] is False


def test_convert_grounded_flag_flows_through():
    from tests.test_convert import CONVERT_JSON, _CONVERT_BODY

    store, embedder = _fresh_store(), HashEmbedder()
    _seed(store, embedder, ["# LINQ\n\nWhere filters a sequence."])
    provider = _JsonProvider([json.dumps(CONVERT_JSON)])
    client = _client_with(provider=provider, embedder=embedder, store=store)
    resp = client.post("/api/convert", json=_CONVERT_BODY)
    assert resp.status_code == 200, resp.text
    assert resp.json()["grounded"] is True
