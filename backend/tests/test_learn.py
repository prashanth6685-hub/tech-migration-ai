"""Phase 4 learning endpoint tests. The LLM is faked via dependency override."""
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


PATH_JSON = {
    "path_title": "Java/Spring developer to C#/.NET 8",
    "modules": [
        {
            "title": "C# fundamentals",
            "why_this_module": "Ground the syntax you will see everywhere in .NET.",
            "topics": [
                {
                    "title": "Variables and types",
                    "known_equivalent": "Java variables and primitive types",
                    "new_in_target": False,
                    "estimated_minutes": 30,
                }
            ],
        },
        {
            "title": "Java to C# differences",
            "why_this_module": "Where your habits need updating.",
            "topics": [
                {
                    "title": "LINQ",
                    "known_equivalent": "Java Streams",
                    "new_in_target": False,
                    "estimated_minutes": 60,
                }
            ],
        },
    ],
}

_PATH_BODY = {
    "known": [
        {"name": "Java", "version": "17"},
        {"name": "Spring Boot", "version": "3.2"},
    ],
    "target_tech": "C#",
    "target_version": ".NET 8",
    "experience": "advanced",
    "goal": "productive",
}


def test_learn_path_returns_modules_and_topics():
    provider = _JsonProvider([json.dumps(PATH_JSON)])
    client = _client_with(provider)
    resp = client.post("/api/learn/path", json=_PATH_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["path_title"]
    assert len(body["modules"]) == 2
    topics = body["modules"][1]["topics"]
    assert topics[0]["title"] == "LINQ"
    assert topics[0]["known_equivalent"] == "Java Streams"
    assert topics[0]["estimated_minutes"] == 60


def test_learn_path_sends_skip_topics_to_prompt():
    provider = _JsonProvider([json.dumps(PATH_JSON)])
    client = _client_with(provider)
    resp = client.post(
        "/api/learn/path",
        json={**_PATH_BODY, "skip_topics": ["Variables and types"]},
    )
    assert resp.status_code == 200
    prompt = provider.last_messages[0]["content"]
    assert "Variables and types" in prompt
    assert "do NOT include them" in prompt
    assert "Java" in prompt and "C#" in prompt


def test_learn_path_rejects_empty_known():
    provider = _JsonProvider([json.dumps(PATH_JSON)])
    client = _client_with(provider)
    resp = client.post("/api/learn/path", json={**_PATH_BODY, "known": []})
    assert resp.status_code == 422
    assert provider.calls == 0


LESSON_JSON = {
    "topic": "LINQ",
    "level": 3,
    "level_name": "Experienced",
    "what_stays_same": "The idea of filtering and projecting collections declaratively.",
    "what_changes": "LINQ is language-integrated with query syntax and extension methods on IEnumerable.",
    "why_different": "C# chose language-integrated queries so filtering composes with the type system.",
    "source_example": "employees.stream().filter(e -> e.getAge() > 30).toList();",
    "target_example": "employees.Where(e => e.Age > 30).ToList();",
    "idiomatic_target": "var result = employees.Where(e => e.Age > 30).ToList();",
    "new_capabilities": ["Query syntax", "Deferred execution"],
    "production_notes": "Profile large datasets; avoid re-enumerating queries in hot paths.",
}

_TOPIC_BODY = {
    "known": [{"name": "Java"}],
    "target_tech": "C#",
    "target_version": ".NET 8",
    "topic": "LINQ",
    "level": 3,
}


def test_learn_topic_returns_lesson_with_examples():
    provider = _JsonProvider([json.dumps(LESSON_JSON)])
    client = _client_with(provider)
    resp = client.post("/api/learn/topic", json=_TOPIC_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["topic"] == "LINQ"
    assert body["level"] == 3
    assert body["level_name"] == "Experienced"
    assert "stream" in body["source_example"]
    assert "Where" in body["target_example"]
    assert body["new_capabilities"]


def test_learn_topic_rejects_invalid_level():
    provider = _JsonProvider([json.dumps(LESSON_JSON)])
    client = _client_with(provider)
    resp = client.post("/api/learn/topic", json={**_TOPIC_BODY, "level": 5})
    assert resp.status_code == 422
    assert provider.calls == 0


EXERCISES_JSON = {
    "exercises": [
        {
            "kind": "basic",
            "title": "Filter with Where",
            "prompt": "Filter a list of employees to those over 30 using LINQ.",
            "starter_code": "var employees = GetEmployees();",
        },
        {
            "kind": "intermediate",
            "title": "Group and count",
            "prompt": "Group employees by department and count each group.",
            "starter_code": "",
        },
        {
            "kind": "production",
            "title": "Paginated query",
            "prompt": "Implement paged fetching from a DbSet with ordering.",
            "starter_code": "",
        },
        {
            "kind": "migration",
            "title": "Streams to LINQ",
            "prompt": "Convert this Java Streams snippet to LINQ:\n```java\nlist.stream().map(String::toUpperCase).collect(toList());\n```",
            "starter_code": "",
        },
    ]
}

_EXERCISES_BODY = {
    "known": [{"name": "Java"}],
    "target_tech": "C#",
    "topic": "LINQ",
    "level": 2,
}


def test_learn_exercises_returns_four_kinds():
    provider = _JsonProvider([json.dumps(EXERCISES_JSON)])
    client = _client_with(provider)
    resp = client.post("/api/learn/exercises", json=_EXERCISES_BODY)
    assert resp.status_code == 200
    kinds = [e["kind"] for e in resp.json()["exercises"]]
    assert kinds == ["basic", "intermediate", "production", "migration"]


REVIEW_JSON = {
    "verdict": "partial",
    "correct_parts": ["Used Where correctly for filtering."],
    "incorrect_parts": ["Called ToList() twice, enumerating the query twice."],
    "better_implementation": "var result = employees.Where(e => e.Age > 30).ToList();",
    "best_practices": ["Materialize once at the end of the query chain."],
}

_REVIEW_BODY = {
    "exercise_title": "Filter with Where",
    "exercise_prompt": "Filter employees over 30 using LINQ.",
    "target_tech": "C#",
    "solution": "var result = employees.Where(e => e.Age > 30).ToList();",
}


def test_learn_review_returns_verdict_and_better_code():
    provider = _JsonProvider([json.dumps(REVIEW_JSON)])
    client = _client_with(provider)
    resp = client.post("/api/learn/review", json=_REVIEW_BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "partial"
    assert body["correct_parts"]
    assert body["incorrect_parts"]
    assert "Where" in body["better_implementation"]
    assert body["best_practices"]


def test_learn_review_rejects_empty_solution():
    provider = _JsonProvider([json.dumps(REVIEW_JSON)])
    client = _client_with(provider)
    resp = client.post("/api/learn/review", json={**_REVIEW_BODY, "solution": ""})
    assert resp.status_code == 422
    assert provider.calls == 0


def test_extract_json_prefers_whole_body_over_inner_fences():
    # A code value inside valid JSON may itself contain ``` fences —
    # the parser must not grab the inner fence.
    from llm.structured import extract_json

    raw = '{"prompt": "Convert this:\\n```java\\nlist.stream();\\n```"}'
    assert extract_json(raw) == {
        "prompt": "Convert this:\n```java\nlist.stream();\n```"
    }


def test_learn_garbage_json_returns_502_with_raw():
    provider = _JsonProvider(["not json", "still not json"])
    client = _client_with(provider)
    resp = client.post("/api/learn/path", json=_PATH_BODY)
    assert resp.status_code == 502
    assert "raw" in resp.json()["detail"]
    assert provider.calls == 2
