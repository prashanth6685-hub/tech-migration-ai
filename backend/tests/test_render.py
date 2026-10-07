"""Render-deployment tests: OpenAI-compatible provider/embedder, ingest 503,
health fields, embedder factory. No network — everything faked."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from llm.provider import get_provider
from main import app
from rag.embeddings import (
    Embedder,
    EmbedderUnavailableError,
    OpenAIEmbedder,
    embedding_provider_name,
    get_embedder,
    reset_embedder,
)
from rag.vector_store import InMemoryStore, get_vector_store


# --- fakes ---------------------------------------------------------------


class _EmbedFakeClient:
    def __init__(self, vectors):
        self._vectors = vectors
        self.last_payload = None
        self.last_headers = None

    async def post(self, url, json=None, headers=None):
        assert url == "/embeddings"
        self.last_payload = json
        self.last_headers = headers
        data = [
            {"index": i, "embedding": v} for i, v in enumerate(self._vectors)
        ]
        return httpx.Response(
            200,
            json={"data": data},
            request=httpx.Request("POST", url),
        )

    async def aclose(self):
        pass


class _BrokenEmbedder(Embedder):
    @property
    def dimension(self):
        return 8

    async def embed(self, texts):
        raise EmbedderUnavailableError("fake outage")


# --- OpenAIEmbedder -------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_embedder_posts_and_preserves_order(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    vecs = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    client = _EmbedFakeClient(vecs)
    emb = OpenAIEmbedder(client=client)
    out = await emb.embed(["a", "b", "c"])
    assert out == vecs
    assert emb.dimension == 2
    assert client.last_payload["model"] == "text-embedding-3-small"
    assert client.last_payload["input"] == ["a", "b", "c"]
    assert client.last_headers["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_openai_embedder_empty_input_no_call(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    emb = OpenAIEmbedder(client=_EmbedFakeClient([]))
    assert await emb.embed([]) == []


@pytest.mark.asyncio
async def test_openai_embedder_missing_key():
    emb = OpenAIEmbedder(client=_EmbedFakeClient([]), api_key=None)
    # ensure env has no key for this check
    import os

    old = os.environ.pop("OPENAI_API_KEY", None)
    try:
        with pytest.raises(EmbedderUnavailableError, match="OPENAI_API_KEY"):
            await emb.embed(["x"])
    finally:
        if old is not None:
            os.environ["OPENAI_API_KEY"] = old


# --- embedder factory ----------------------------------------------------


def test_embedding_provider_name_defaults_to_ollama(monkeypatch):
    monkeypatch.delenv("EMBEDDING_PROVIDER", raising=False)
    assert embedding_provider_name() == "ollama"


def test_get_embedder_factory_openai(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    reset_embedder()
    try:
        emb = get_embedder()
        assert isinstance(emb, OpenAIEmbedder)
    finally:
        reset_embedder()


def test_get_embedder_factory_rejects_unknown(monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "bogus")
    reset_embedder()
    try:
        with pytest.raises(ValueError, match="Unknown EMBEDDING_PROVIDER"):
            get_embedder()
    finally:
        reset_embedder()


# --- ingest 503 ----------------------------------------------------------


def test_ingest_returns_503_when_embedder_unavailable():
    app.dependency_overrides[get_embedder] = lambda: _BrokenEmbedder()
    app.dependency_overrides[get_vector_store] = lambda: InMemoryStore()
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/knowledge/ingest",
            json={
                "items": [{"title": "doc", "markdown": "# Hello\n\nSome text here."}],
                "tech": "csharp",
                "version": "8",
            },
        )
        assert resp.status_code == 503, resp.text
        assert "embeddings unavailable" in resp.json()["detail"]
        assert "EMBEDDING_PROVIDER=openai" in resp.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_embedder, None)
        app.dependency_overrides.pop(get_vector_store, None)


# --- health fields -------------------------------------------------------


def test_health_reports_embedding_provider_and_vector_store(monkeypatch):
    from llm.provider import AIProvider

    class _FakeProvider(AIProvider):
        name = "openai"
        model = "openai/gpt-oss-120b"

        def chat_stream(self, messages, system=None):
            return self._gen()

        async def _gen(self):
            yield "x"

        async def ping(self):
            return True

    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
    app.dependency_overrides[get_provider] = lambda: _FakeProvider()
    app.dependency_overrides[get_vector_store] = lambda: InMemoryStore()
    try:
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["provider"] == "openai"
        assert body["model"] == "openai/gpt-oss-120b"
        assert body["embedding_provider"] == "openai"
        assert body["vector_store"] == "memory"
    finally:
        app.dependency_overrides.pop(get_provider, None)
        app.dependency_overrides.pop(get_vector_store, None)
