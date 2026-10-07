"""AI provider abstraction.

All LLM access goes through AIProvider so the model and vendor can be
swapped by configuration alone. Ships with Ollama (local, free) and
OpenAICompatProvider (any OpenAI-compatible chat API — OpenAI, Groq, ...).
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


class OpenAICompatProvider(AIProvider):
    """Any OpenAI-compatible chat API: OpenAI, Groq, Together, etc.

    Talks to ``{base_url}/chat/completions`` with OpenAI-format streaming
    SSE (``data:`` lines carrying ``choices[0].delta.content``, terminated by
    ``data: [DONE]``). Configure via env:

    - ``OPENAI_API_KEY``      (required) — e.g. a free key from console.groq.com
    - ``OPENAI_BASE_URL``     (default https://api.openai.com/v1)
    - ``OPENAI_MODEL``        (default gpt-4o-mini; on Groq use e.g.
      ``openai/gpt-oss-120b``)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        client: Optional[Any] = None,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/")
        self._model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        # None means "read env lazily", so tests can inject or monkeypatch env.
        self._api_key = api_key
        # Optional injected HTTP client (used by tests to mock the API).
        self._client = client

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    def _key(self) -> str:
        key = (
            self._api_key
            if self._api_key is not None
            else os.environ.get("OPENAI_API_KEY", "")
        )
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Set it to your provider key "
                "(e.g. a free Groq key) and AI_PROVIDER=openai."
            )
        return key

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key()}"}

    def _new_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, timeout=httpx.Timeout(120.0))

    def chat_stream(
        self, messages: list[dict[str, str]], system: Optional[str] = None
    ) -> AsyncIterator[str]:
        return self._chat_stream_impl(messages, system)

    async def _chat_stream_impl(
        self, messages: list[dict[str, str]], system: Optional[str]
    ) -> AsyncIterator[str]:
        headers = self._headers()  # raises early with a clear message
        payload_messages = list(messages)
        if system:
            payload_messages = [{"role": "system", "content": system}] + payload_messages
        payload = {"model": self._model, "messages": payload_messages, "stream": True}

        client = self._client if self._client is not None else self._new_client()
        try:
            async with client.stream(
                "POST", "/chat/completions", json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    try:
                        body = await resp.aread()
                        detail = body.decode("utf-8", "replace")[:500]
                    except Exception:
                        detail = "<unreadable>"
                    raise RuntimeError(
                        f"chat API at {self.base_url} returned "
                        f"HTTP {resp.status_code}: {detail}"
                    )
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices") or []
                    delta = (choices[0].get("delta") or {}) if choices else {}
                    content = delta.get("content")
                    if content:
                        yield content
        finally:
            if self._client is None:
                await client.aclose()

    async def ping(self) -> bool:
        try:
            headers = self._headers()
        except RuntimeError:
            return False
        client = self._client if self._client is not None else self._new_client()
        try:
            resp = await client.get("/models", headers=headers)
            return resp.status_code == 200
        except Exception:
            return False
        finally:
            if self._client is None:
                await client.aclose()


def get_provider() -> AIProvider:
    """Factory: picks the provider from the AI_PROVIDER env var (default 'ollama')."""
    key = os.environ.get("AI_PROVIDER", "ollama").strip().lower()
    if key == "ollama":
        return OllamaProvider()
    if key == "openai":
        return OpenAICompatProvider()
    raise ValueError(
        f"Unknown AI_PROVIDER {key!r}: expected 'ollama' or 'openai'."
    )
