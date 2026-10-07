"""AI provider abstraction.

All LLM access goes through AIProvider so the model and vendor can be
swapped by configuration alone. Phase 1 ships Ollama (local, free);
OpenAIProvider is a stub that activates once keys are configured.
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

import httpx


class AIProvider(ABC):
    """Port for LLM chat. Business logic depends only on this interface."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider key, e.g. 'ollama' or 'openai'."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Model name this provider will use."""

    @abstractmethod
    def chat_stream(
        self, messages: list[dict[str, str]], system: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Yield answer tokens in order. `messages` are {role, content} dicts
        (roles: system/user/assistant). `system` is prepended as a system
        message when provided."""

    @abstractmethod
    async def ping(self) -> bool:
        """True when the underlying LLM is reachable right now."""


class OllamaProvider(AIProvider):
    """Local LLM via the Ollama HTTP API (http://localhost:11434 by default)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        ).rstrip("/")
        self._model = model or os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:14b")
        # Optional injected HTTP client (used by tests to mock Ollama).
        self._client = client

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(120.0))

    def chat_stream(
        self, messages: list[dict[str, str]], system: Optional[str] = None
    ) -> AsyncIterator[str]:
        return self._chat_stream_impl(messages, system)

    async def _chat_stream_impl(
        self, messages: list[dict[str, str]], system: Optional[str]
    ) -> AsyncIterator[str]:
        payload_messages = list(messages)
        if system:
            payload_messages = [{"role": "system", "content": system}] + payload_messages
        payload = {"model": self._model, "messages": payload_messages, "stream": True}

        client = self._client if self._client is not None else self._new_client()
        try:
            async with client.stream("POST", "/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    content = (data.get("message") or {}).get("content")
                    if content:
                        yield content
                    if data.get("done"):
                        break
        finally:
            if self._client is None:
                await client.aclose()

    async def ping(self) -> bool:
        client = self._client if self._client is not None else self._new_client()
        try:
            resp = await client.get("/api/version")
            return resp.status_code == 200
        except Exception:
            return False
        finally:
            if self._client is None:
                await client.aclose()


class OpenAIProvider(AIProvider):
    """Cloud provider stub. Activates once OPENAI_API_KEY is configured."""

    def __init__(self) -> None:
        self._model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    async def chat_stream(
        self, messages: list[dict[str, str]], system: Optional[str] = None
    ) -> AsyncIterator[str]:
        raise NotImplementedError(
            "OpenAI provider is not configured: set OPENAI_API_KEY and "
            "AI_PROVIDER=openai. Phase 1 runs on local Ollama."
        )
        yield  # make this an async generator

    async def ping(self) -> bool:
        return False


def get_provider() -> AIProvider:
    """Factory: picks the provider from the AI_PROVIDER env var (default 'ollama')."""
    key = os.environ.get("AI_PROVIDER", "ollama").strip().lower()
    if key == "ollama":
        return OllamaProvider()
    if key == "openai":
        return OpenAIProvider()
    raise ValueError(
        f"Unknown AI_PROVIDER {key!r}: expected 'ollama' or 'openai'."
    )
