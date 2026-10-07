"""Embedding models behind one interface.

Production: OllamaEmbedder calls the local Ollama /api/embeddings endpoint
(default model nomic-embed-text) — free, offline, no API keys.
OpenAIEmbedder calls any OpenAI-compatible /embeddings endpoint (OpenAI,
...). Note: Groq is chat-only and has no embeddings endpoint, so with
Groq as the chat provider the knowledge-base ingest degrades gracefully
(HTTP 503) until an embeddings-capable endpoint is configured.
Tests: HashEmbedder is deterministic and needs no network.
"""
from __future__ import annotations

import hashlib
import math
import os
from abc import ABC, abstractmethod
from typing import Optional

import httpx


class EmbedderUnavailableError(Exception):
    """The configured embedder cannot be reached or is not configured.

    Ingestion surfaces this as HTTP 503 (not 500): embeddings are an
    optional capability, and the message tells the operator how to fix it.
    """


class Embedder(ABC):
    """Port for text embeddings. Business logic depends only on this."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimension this embedder produces."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts, preserving order."""


class OllamaEmbedder(Embedder):
    """Local embeddings via the Ollama HTTP API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        ).rstrip("/")
        self._model = model or os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")
        self._client = client
        self._dimension: Optional[int] = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        # nomic-embed-text is 768 dims; resolved lazily on first embed.
        return self._dimension or 768

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(120.0))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._client if self._client is not None else self._new_client()
        try:
            vectors: list[list[float]] = []
            for text in texts:
                try:
                    resp = await client.post(
                        "/api/embeddings", json={"model": self._model, "prompt": text}
                    )
                    resp.raise_for_status()
                except Exception as exc:
                    raise EmbedderUnavailableError(
                        f"ollama embeddings unavailable at {self.base_url}: {exc}"
                    )
                vec = resp.json()["embedding"]
                vectors.append([float(x) for x in vec])
            if vectors and self._dimension is None:
                self._dimension = len(vectors[0])
            return vectors
        finally:
            if self._client is None:
                await client.aclose()


class OpenAIEmbedder(Embedder):
    """Embeddings via any OpenAI-compatible /embeddings endpoint.

    Env:
    - ``OPENAI_API_KEY``          (required)
    - ``OPENAI_BASE_URL``         (default https://api.openai.com/v1)
    - ``OPENAI_EMBEDDING_MODEL``  (default text-embedding-3-small)

    Note: Groq offers no embeddings endpoint, so with Groq configured this
    raises EmbedderUnavailableError and knowledge-base ingest answers 503.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self._model = model or os.environ.get(
            "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
        )
        self._api_key = api_key
        self._client = client
        self._dimension: Optional[int] = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        # text-embedding-3-small is 1536 dims; resolved lazily on first embed.
        return self._dimension or 1536

    def _key(self) -> str:
        key = (
            self._api_key
            if self._api_key is not None
            else os.environ.get("OPENAI_API_KEY", "")
        )
        if not key:
            raise EmbedderUnavailableError(
                "OPENAI_API_KEY is not set: cannot use the OpenAI embeddings endpoint"
            )
        return key

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(120.0))

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        headers = {"Authorization": f"Bearer {self._key()}"}
        client = self._client if self._client is not None else self._new_client()
        try:
            try:
                resp = await client.post(
                    "/embeddings",
                    json={"model": self._model, "input": texts},
                    headers=headers,
                )
                resp.raise_for_status()
                items = resp.json()["data"]
            except EmbedderUnavailableError:
                raise
            except Exception as exc:
                raise EmbedderUnavailableError(
                    f"embeddings unavailable at {self.base_url}: {exc}"
                )
            # Preserve input order regardless of response ordering.
            vectors: list[Optional[list[float]]] = [None] * len(texts)
            for item in items:
                vectors[item["index"]] = [float(x) for x in item["embedding"]]
            if any(v is None for v in vectors):
                raise EmbedderUnavailableError(
                    f"embeddings response from {self.base_url} was incomplete"
                )
            out = [v for v in vectors if v is not None]
            if out and self._dimension is None:
                self._dimension = len(out[0])
            return out
        finally:
            if self._client is None:
                await client.aclose()


class HashEmbedder(Embedder):
    """Deterministic test embedder: no network, stable across runs.

    Hashes each text into `dimension` buckets and L2-normalizes. Similar
    texts share buckets, so nearest-neighbor search behaves sanely in tests.
    """

    def __init__(self, dimension: int = 64) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self._dimension
            # Token-level hashing: shared words -> shared buckets.
            for token in text.lower().split():
                h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
                vec[h % self._dimension] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


_embedder: Optional[Embedder] = None


def embedding_provider_name() -> str:
    """Active embedder key from EMBEDDING_PROVIDER (default 'ollama')."""
    return os.environ.get("EMBEDDING_PROVIDER", "ollama").strip().lower() or "ollama"


def get_embedder() -> Embedder:
    """Singleton embedder picked by EMBEDDING_PROVIDER ('ollama'|'openai').

    Override in tests via FastAPI dependency_overrides.
    """
    global _embedder
    if _embedder is None:
        key = embedding_provider_name()
        if key == "ollama":
            _embedder = OllamaEmbedder()
        elif key == "openai":
            _embedder = OpenAIEmbedder()
        else:
            raise ValueError(
                f"Unknown EMBEDDING_PROVIDER {key!r}: expected 'ollama' or 'openai'."
            )
    return _embedder


def reset_embedder() -> None:
    """Drop the cached singleton (tests only)."""
    global _embedder
    _embedder = None
