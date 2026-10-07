"""Phase 3 conversion endpoint tests. The LLM is faked via dependency override."""
import json

import pytest
from fastapi.testclient import TestClient

from llm.provider import AIProvider, get_provider
from main import app


class _JsonProvider(AIProvider):
    """Yields one canned response (string or list of strings, one per call)."""

    name = "fake"
    model = "fake-model"

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.last_messages = None

    async def chat_stream(self, messages, system=None):
        self.calls += 1
        self.last_messages = messages
        yield self._responses[min(self.calls - 1, len(self._responses) - 1)]

    async def ping(self):
        return True


def _client_with(provider):
    app.dependency_overrides[get_provider] = lambda: provider
    return TestClient(app)


CONVERT_JSON = {
    "source_code": (
        "List<Employee> result = new ArrayList<>();\n"
        "for (Employee e : employees) {\n"
        "    if (e.getAge() > 30) result.add(e);\n"
        "}"
    ),
    "direct_translation": (
        "var result = new List<Employee>();\n"
        "foreach (var e in employees)\n"
        "{\n"
        "    if (e.Age > 30) result.Add(e);\n"
        "}"
    ),
    "idiomatic_target": "var result = employees.Where(e => e.Age > 30).ToList();",
    "modern_target": "var result = employees.Where(e => e.Age > 30).ToList();",
    "equivalence": "conceptual",
    "explanation": {
        "what_changed": ["for loop replaced with LINQ Where + ToList"],
        "why_changed": ["LINQ is the declarative idiom for collection filtering in C#"],
        "target_differences": "C# properties replace Java getters; LINQ uses deferred execution.",
        "new_capabilities": ["Composable queries, deferred execution"],
        "performance_notes": "Deferred execution avoids intermediate lists; call ToList() once at the end.",
        "common_mistakes": ["Calling ToList() too early and losing deferred execution."],
        "modern_note": "No newer feature improves this snippet beyond idiomatic LINQ.",
    },
}

_CONVERT_BODY = {
    "source_tech": "Java",
    "source_version": "17",
    "target_tech": "C#",
    "target_version": ".NET 8",
    "source_code": CONVERT_JSON["source_code"],
}


def test_convert_returns_all_four_blocks_and_explanation():
    provider = _JsonProvider([json.dumps(CONVERT_JSON)])
    client = _client_with(provider)
    resp = client.post("/api/convert", json=_CONVERT_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_code"] == CONVERT_JSON["source_code"]
    assert "foreach" in body["direct_translation"]
    assert "Where" in body["idiomatic_target"]
    assert body["modern_target"]
    assert body["equivalence"] == "conceptual"
    expl = body["explanation"]
    assert expl["what_changed"]
    assert expl["why_changed"]
    assert expl["target_differences"]
    assert "No newer feature" in expl["modern_note"]


def test_convert_passes_style_hint_and_no_placeholder_rule():
    provider = _JsonProvider([json.dumps(CONVERT_JSON)])
    client = _client_with(provider)
    resp = client.post(
        "/api/convert",
        json={**_CONVERT_BODY, "style_hint": "spring-controller"},
    )
    assert resp.status_code == 200
    prompt = provider.last_messages[0]["content"]
    assert "spring-controller" in prompt
    assert "NEVER" in prompt and "..." in prompt  # no-ellipsis hard rule ships


def test_convert_rejects_incomplete_json_then_retries():
    bad = dict(CONVERT_JSON)
    del bad["modern_target"]  # missing required field -> validation error -> retry
    provider = _JsonProvider([json.dumps(bad), json.dumps(CONVERT_JSON)])
    client = _client_with(provider)
    resp = client.post("/api/convert", json=_CONVERT_BODY)
    assert resp.status_code == 200
    assert provider.calls == 2
    assert resp.json()["modern_target"]


def test_convert_garbage_json_returns_502_with_raw():
    provider = _JsonProvider(["not json", "still not json"])
    client = _client_with(provider)
    resp = client.post("/api/convert", json=_CONVERT_BODY)
    assert resp.status_code == 502
    assert "raw" in resp.json()["detail"]


def test_convert_rejects_empty_code():
    provider = _JsonProvider([json.dumps(CONVERT_JSON)])
    client = _client_with(provider)
    resp = client.post(
        "/api/convert",
        json={**_CONVERT_BODY, "source_code": ""},
    )
    assert resp.status_code == 422
    assert provider.calls == 0  # never reached the model


def test_convert_rejects_missing_target():
    provider = _JsonProvider([json.dumps(CONVERT_JSON)])
    client = _client_with(provider)
    resp = client.post("/api/convert", json={"source_tech": "Java", "source_code": "x();"})
    assert resp.status_code == 422
