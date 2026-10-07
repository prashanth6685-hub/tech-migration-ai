"""Chat endpoint tests. The LLM is faked via dependency override."""
import json

from fastapi.testclient import TestClient

from llm.provider import AIProvider, get_provider
from main import app


class _FakeProvider(AIProvider):
    name = "fake"
    model = "fake-model"

    async def chat_stream(self, messages, system=None):
        yield "Hello "
        yield "world"

    async def ping(self):
        return True


class _ErrorProvider(AIProvider):
    name = "fake"
    model = "fake-model"

    async def chat_stream(self, messages, system=None):
        raise RuntimeError("boom")
        yield  # pragma: no cover - make it an async generator

    async def ping(self):
        return False


def _client_with(provider):
    app.dependency_overrides[get_provider] = lambda: provider
    return TestClient(app)


def _sse_events(text):
    events = []
    for chunk in text.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:"):].strip()))
    return events


def test_chat_streams_tokens_then_done():
    client = _client_with(_FakeProvider())
    resp = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    events = _sse_events(resp.text)
    tokens = [e["token"] for e in events if "token" in e]
    assert "".join(tokens) == "Hello world"
    assert events[-1] == {"done": True}


def test_chat_provider_error_yields_error_event():
    client = _client_with(_ErrorProvider())
    resp = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    events = _sse_events(resp.text)
    errors = [e["error"] for e in events if "error" in e]
    assert errors and "boom" in errors[0]
    assert events[-1] == {"done": True}


def test_chat_rejects_empty_messages():
    client = _client_with(_FakeProvider())
    resp = client.post("/api/chat", json={"messages": []})
    assert resp.status_code == 422


def test_chat_rejects_bad_role():
    client = _client_with(_FakeProvider())
    resp = client.post(
        "/api/chat", json={"messages": [{"role": "hacker", "content": "hi"}]}
    )
    assert resp.status_code == 422


def test_health_reports_provider_state():
    client = _client_with(_FakeProvider())
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": "ok",
        "provider": "fake",
        "model": "fake-model",
        "ollama_reachable": True,
        "embedding_provider": "ollama",
        "vector_store": "memory",  # Qdrant is unreachable in tests -> fallback
    }
