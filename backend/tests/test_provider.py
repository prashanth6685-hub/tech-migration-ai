"""Provider contract tests. Ollama is never contacted: HTTP is mocked."""
import json

import httpx
import pytest

from llm.provider import AIProvider, OllamaProvider, OpenAIProvider, get_provider


# --- fakes ---------------------------------------------------------------


class _FakeStream:
    def __init__(self, lines, payload_probe=None):
        self._lines = lines
        self._payload_probe = payload_probe

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeClient:
    """Mimics the subset of httpx.AsyncClient the provider uses."""

    def __init__(self, lines=None, status=200):
        self._lines = lines or []
        self.status = status
        self.last_payload = None

    def stream(self, method, url, json=None):
        assert method == "POST" and url == "/api/chat"
        self.last_payload = json
        return _FakeStream(self._lines)

    async def get(self, url):
        assert url == "/api/version"
        return httpx.Response(self.status, request=httpx.Request("GET", url))


class _FailingClient:
    async def get(self, url):
        raise httpx.ConnectError("connection refused")


def _ndjson(*contents, done=True):
    lines = [
        json.dumps({"message": {"content": c}, "done": False}) for c in contents
    ]
    lines.append(json.dumps({"done": done}))
    return lines


# --- OllamaProvider -------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_chat_stream_yields_tokens_in_order():
    provider = OllamaProvider(
        base_url="http://fake:11434",
        model="test-model",
        client=_FakeClient(_ndjson("Hello ", "world")),
    )
    tokens = [
        t
        async for t in provider.chat_stream([{"role": "user", "content": "hi"}])
    ]
    assert tokens == ["Hello ", "world"]


@pytest.mark.asyncio
async def test_ollama_chat_stream_prepends_system_prompt():
    client = _FakeClient(_ndjson("ok"))
    provider = OllamaProvider(
        base_url="http://fake:11434", model="test-model", client=client
    )
    async for _ in provider.chat_stream(
        [{"role": "user", "content": "hi"}], system="SYS"
    ):
        pass
    assert client.last_payload["model"] == "test-model"
    assert client.last_payload["stream"] is True
    assert client.last_payload["messages"][0] == {"role": "system", "content": "SYS"}
    assert client.last_payload["messages"][1] == {"role": "user", "content": "hi"}


@pytest.mark.asyncio
async def test_ollama_ping_true_when_reachable():
    provider = OllamaProvider(client=_FakeClient(status=200))
    assert await provider.ping() is True


@pytest.mark.asyncio
async def test_ollama_ping_false_when_unreachable():
    provider = OllamaProvider(client=_FailingClient())
    assert await provider.ping() is False


def test_ollama_defaults():
    provider = OllamaProvider()
    assert provider.name == "ollama"
    assert provider.model  # non-empty default model name


# --- OpenAIProvider -------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_provider_is_unconfigured_stub():
    provider = OpenAIProvider()
    assert provider.name == "openai"
    assert await provider.ping() is False
    with pytest.raises(NotImplementedError, match="OPENAI_API_KEY"):
        async for _ in provider.chat_stream([{"role": "user", "content": "hi"}]):
            pass


# --- factory --------------------------------------------------------------


def test_get_provider_defaults_to_ollama(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert isinstance(get_provider(), OllamaProvider)


def test_get_provider_openai(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    provider = get_provider()
    assert isinstance(provider, OpenAIProvider)


def test_get_provider_rejects_unknown(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "bogus")
    with pytest.raises(ValueError, match="Unknown AI_PROVIDER"):
        get_provider()


def test_provider_is_abstract():
    with pytest.raises(TypeError):
        AIProvider()  # type: ignore
