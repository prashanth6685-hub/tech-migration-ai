"""Embedding models behind one interface.

Production: OllamaEmbedder calls the local Ollama /api/embeddings endpoint
(default model nomic-embed-text) — free, offline, no API keys.
Tests: HashEmbedder is deterministic and needs no network.
"""
from __future__ import annotations

import hashlib
import math
import os
from abc import ABC, abstractmethod
from typing import Optional

import httpx


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
                resp = await client.post(
                    "/api/embeddings", json={"model": self._model, "prompt": text}
                )
                resp.raise_for_status()
                vec = resp.json()["embedding"]
                vectors.append([float(x) for x in vec])
            if vectors and self._dimension is None:
                self._dimension = len(vectors[0])
            return vectors
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


def get_embedder() -> Embedder:
    """Singleton embedder (Ollama). Override in tests via dependency_overrides."""
    global _embedder
    if _embedder is None:
        _embedder = OllamaEmbedder()
    return _embedder


def reset_embedder() -> None:
    """Drop the cached singleton (tests only)."""
    global _embedder
    _embedder = None
