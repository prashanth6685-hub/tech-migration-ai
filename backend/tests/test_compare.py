"""Phase 2 comparison endpoint tests. The LLM is faked via dependency override."""
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


CONCEPT_JSON = {
    "source_technology": "Java 17",
    "target_technology": "C# (.NET 8)",
    "concept": "CompletableFuture",
    "equivalence": "conceptual",
    "source_implementation": "CompletableFuture.supplyAsync(() -> 42);",
    "target_implementation": "var t = Task.Run(() => 42);",
    "key_difference": "Task underpins async/await with language support; exception and cancellation models differ.",
    "target_specific_improvement": "await integrates with the language; ValueTask avoids allocations.",
    "common_migration_problem": "Blocking on .Result causes deadlocks like .get() misuse.",
    "recommended_approach": "Use async/await end to end; avoid .Result/.Wait().",
}

MAPPING_JSON = {
    "rows": [
        {"source": "Java", "target": "C#", "equivalence": "conceptual", "note": "Both statically typed; nullability and records differ."},
        {"source": "Maven", "target": "NuGet", "equivalence": "conceptual", "note": "Dependency managers; build lifecycle roles differ."},
        {"source": "application.properties", "target": "appsettings.json", "equivalence": "partial", "note": "Different format and provider layering model."},
    ]
}

CODE_JSON = {
    "source_code": "List<String> names = List.of(\"a\");",
    "target_code": 'var names = new List<string> { "a" };',
    "notes": ["Java List.of is immutable; C# List<T> is mutable."],
}


def test_concept_returns_validated_json():
    provider = _JsonProvider([json.dumps(CONCEPT_JSON)])
    client = _client_with(provider)
    resp = client.post(
        "/api/compare/concept",
        json={
            "source_tech": "Java",
            "source_version": "17",
            "target_tech": "C#",
            "target_version": ".NET 8",
            "concept": "CompletableFuture",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["equivalence"] == "conceptual"
    assert body["concept"] == "CompletableFuture"
    assert "Task.Run" in body["target_implementation"]
    # The honest-labeling rule must reach the model.
    assert "NEVER label something \"exact\"" in provider.last_messages[0]["content"]


def test_concept_rejects_bad_equivalence_label():
    bad = dict(CONCEPT_JSON, equivalence="almost")
    provider = _JsonProvider([json.dumps(bad), json.dumps(CONCEPT_JSON)])
    client = _client_with(provider)
    resp = client.post(
        "/api/compare/concept",
        json={"source_tech": "Java", "target_tech": "C#", "concept": "CompletableFuture"},
    )
    assert resp.status_code == 200
    assert provider.calls == 2  # retried once with the validation error
    assert resp.json()["equivalence"] == "conceptual"


def test_concept_garbage_json_returns_502_with_raw():
    provider = _JsonProvider(["this is not json at all", "still not json"])
    client = _client_with(provider)
    resp = client.post(
        "/api/compare/concept",
        json={"source_tech": "Java", "target_tech": "C#", "concept": "CompletableFuture"},
    )
    assert resp.status_code == 502
    assert "raw" in resp.json()["detail"]
    assert "still not json" in resp.json()["detail"]["raw"]


def test_concept_422_on_empty_concept():
    client = _client_with(_JsonProvider([json.dumps(CONCEPT_JSON)]))
    resp = client.post(
        "/api/compare/concept",
        json={"source_tech": "Java", "target_tech": "C#", "concept": ""},
    )
    assert resp.status_code == 422


def test_mapping_returns_rows():
    provider = _JsonProvider([json.dumps(MAPPING_JSON)])
    client = _client_with(provider)
    resp = client.post(
        "/api/compare/mapping",
        json={
            "source_stack": {"language": "Java", "framework": "Spring Boot", "build": "Maven"},
            "target_stack": {"language": "C#", "framework": "ASP.NET Core", "build": "NuGet"},
        },
    )
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert len(rows) == 3
    assert all(r["equivalence"] in ("exact", "conceptual", "partial", "none") for r in rows)


def test_code_compare_side_by_side():
    provider = _JsonProvider([json.dumps(CODE_JSON)])
    client = _client_with(provider)
    resp = client.post(
        "/api/compare/code",
        json={
            "source_tech": "Java",
            "target_tech": "C#",
            "source_code": 'List<String> names = List.of("a");',
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "List<string>" in body["target_code"]
    assert len(body["notes"]) == 1


def test_code_compare_422_on_empty_and_too_long():
    client = _client_with(_JsonProvider([json.dumps(CODE_JSON)]))
    assert (
        client.post(
            "/api/compare/code",
            json={"source_tech": "Java", "target_tech": "C#", "source_code": ""},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/compare/code",
            json={"source_tech": "Java", "target_tech": "C#", "source_code": "x" * 12001},
        ).status_code
        == 422
    )


def test_catalog_lists_real_technologies():
    client = _client_with(_JsonProvider([]))
    resp = client.get("/api/tech/catalog")
    assert resp.status_code == 200
    catalog = resp.json()
    for key in ("languages", "frameworks", "databases", "orms", "testing", "build", "deployment", "runtimes"):
        assert key in catalog
    java = next(t for t in catalog["languages"] if t["id"] == "java")
    assert "17" in java["versions"] and "21" in java["versions"]
    csharp = next(t for t in catalog["languages"] if t["id"] == "csharp")
    assert csharp["versions"]
    spring = next(t for t in catalog["frameworks"] if t["id"] == "spring-boot")
    assert "3.4" in spring["versions"]
