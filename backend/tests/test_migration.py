"""Phase 6 repository-analysis tests. No LLM, no network.

A fixture ZIP of a mini Spring Boot app is built in-test and uploaded;
detection, scoring, zip-slip protection, and the analyze endpoint (fake
provider) are exercised. Created project dirs are cleaned up afterwards.
"""
import io
import json
import shutil
import zipfile

import pytest
from fastapi.testclient import TestClient

from analyzers.detect import detect_project
from analyzers.scoring import AREAS, WEIGHTS, compute_readiness
from api.migration import PROJECTS_DIR
from llm.provider import AIProvider, get_provider
from main import app
from rag.embeddings import HashEmbedder, get_embedder
from rag.vector_store import InMemoryStore, get_vector_store

POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.2.0</version>
  </parent>
  <groupId>com.example</groupId>
  <artifactId>demo</artifactId>
  <version>0.0.1</version>
  <properties><java.version>17</java.version></properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-data-jpa</artifactId>
    </dependency>
    <dependency>
      <groupId>org.postgresql</groupId>
      <artifactId>postgresql</artifactId>
      <scope>runtime</scope>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-test</artifactId>
      <scope>test</scope>
    </dependency>
  </dependencies>
</project>
"""

APP_JAVA = """package com.example;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
@SpringBootApplication
public class DemoApplication {
    public static void main(String[] args) {
        SpringApplication.run(DemoApplication.class, args);
    }
}
"""

ENTITY_JAVA = """package com.example;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
@Entity
public class Widget {
    @Id private Long id;
    private String name;
}
"""

TEST_JAVA = """package com.example;
import org.junit.jupiter.api.Test;
class DemoApplicationTests {
    @Test void contextLoads() {}
}
"""

PROPS = """spring.datasource.url=jdbc:postgresql://localhost:5432/demo
spring.datasource.username=demo
spring.datasource.password=supersecret123
server.port=8080
"""

DOCKERFILE = "FROM eclipse-temurin:17-jre\nCOPY target/demo.jar app.jar\n"


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


@pytest.fixture()
def spring_zip() -> bytes:
    return _zip({
        "pom.xml": POM,
        "src/main/java/com/example/DemoApplication.java": APP_JAVA,
        "src/main/java/com/example/Widget.java": ENTITY_JAVA,
        "src/test/java/com/example/DemoApplicationTests.java": TEST_JAVA,
        "src/main/resources/application.properties": PROPS,
        "Dockerfile": DOCKERFILE,
    })


def _client(provider=None):
    if provider is not None:
        app.dependency_overrides[get_provider] = lambda: provider
    else:
        app.dependency_overrides.pop(get_provider, None)
    app.dependency_overrides[get_embedder] = lambda: HashEmbedder()
    app.dependency_overrides[get_vector_store] = lambda: InMemoryStore()
    return TestClient(app)


def _upload(client, payload: bytes, name="app.zip"):
    return client.post(
        "/api/migration/upload",
        files={"file": (name, payload, "application/zip")},
    )


def _cleanup(project_id: str):
    shutil.rmtree(PROJECTS_DIR / project_id, ignore_errors=True)


class _JsonProvider(AIProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, response):
        self._response = response

    async def chat_stream(self, messages, system=None):
        yield self._response

    async def ping(self):
        return True


# ---------------------------------------------------------------------------
# Upload + detection
# ---------------------------------------------------------------------------


def test_upload_detects_spring_boot_stack(spring_zip):
    client = _client()
    resp = _upload(client, spring_zip)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    project_id = body["project_id"]
    try:
        detected = body["detected"]
        langs = {l["name"]: l for l in detected["languages"]}
        assert langs["Java"]["files"] == 3
        assert langs["Java"]["version"] == "17"
        assert "Spring Boot" in detected["frameworks"]
        assert "Maven" in detected["build_systems"]
        assert "JUnit" in detected["testing_frameworks"] or any(
            "junit" in d["name"].lower() or "starter-test" in d["name"]
            for d in detected["dependencies"]
        )
        assert "PostgreSQL" in detected["databases"]
        assert "JPA" in detected["orms"]
        assert "Docker" in detected["deployment"]
        assert any("application.properties" in c for c in detected["config_files"])
        # Hardcoded secret must be flagged red.
        reds = [f for f in detected["findings"]
                if f["severity"] == "red" and f["area"] == "security"]
        assert reds, "expected a red security finding for the inline password"
    finally:
        _cleanup(project_id)


def test_upload_rejects_non_zip():
    client = _client()
    resp = client.post(
        "/api/migration/upload",
        files={"file": ("app.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_rejects_empty_zip():
    client = _client()
    resp = _upload(client, _zip({}))
    assert resp.status_code == 400


def test_zip_slip_is_contained(spring_zip):
    evil = _zip({
        "../../evil.txt": "pwned",
        "/abs.txt": "pwned",
        "ok.txt": "fine",
    })
    client = _client()
    resp = _upload(client, evil)
    assert resp.status_code == 200
    project_id = resp.json()["project_id"]
    try:
        src = PROJECTS_DIR / project_id / "src"
        assert (src / "ok.txt").is_file()
        assert not (PROJECTS_DIR / "evil.txt").exists()
        assert not (PROJECTS_DIR.parent / "abs.txt").exists()
        # Nothing escaped the project dir.
        assert not (PROJECTS_DIR / project_id / "evil.txt").exists()
    finally:
        _cleanup(project_id)


def test_get_project_roundtrip(spring_zip):
    client = _client()
    project_id = _upload(client, spring_zip).json()["project_id"]
    try:
        resp = client.get(f"/api/migration/{project_id}")
        assert resp.status_code == 200
        assert resp.json()["project_id"] == project_id
        assert client.get("/api/migration/nope123").status_code == 404
    finally:
        _cleanup(project_id)


# ---------------------------------------------------------------------------
# Scoring (deterministic)
# ---------------------------------------------------------------------------


def test_scoring_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9
    assert set(WEIGHTS) == set(AREAS)


def test_scoring_sanity_on_detected_project(spring_zip, tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / "pom.xml").write_text(POM)
    (d / "Dockerfile").write_text(DOCKERFILE)
    (d / "application.properties").write_text(PROPS)
    (d / "DemoApplicationTests.java").write_text(TEST_JAVA)
    facts = detect_project(d, file_count=4, total_bytes=100)
    readiness = compute_readiness(facts)
    for area in AREAS:
        assert 0 <= readiness.scores[area] <= 100, area
    expected = round(sum(readiness.scores[a] * WEIGHTS[a] for a in AREAS))
    assert readiness.scores["overall"] == expected
    # Secrets + docker + tests all leave a trace in issues.
    assert any(i.severity == "red" for i in readiness.issues)
    assert any(i.severity == "green" for i in readiness.issues)


# ---------------------------------------------------------------------------
# Analyze endpoint (fake LLM)
# ---------------------------------------------------------------------------

REPORT_JSON = {
    "summary": "A small Spring Boot web app with JPA/PostgreSQL.",
    "migrationDifficulty": "Medium",
    "overallRisk": "Medium",
    "technologyMapping": [
        {"source": "Java", "target": "C#", "equivalence": "conceptual",
         "notes": "Similar OO roots, different runtime."},
        {"source": "Spring Boot", "target": "ASP.NET Core",
         "equivalence": "conceptual", "notes": "DI and middleware differ."},
    ],
    "breakingChanges": ["jakarta.persistence namespace has no direct EF equivalent."],
    "dependencies": ["postgresql driver -> Npgsql."],
    "codeChanges": ["Checked exceptions become unchecked."],
    "configurationChanges": ["application.properties -> appsettings.json."],
    "databaseChanges": ["JPA mappings -> EF Core fluent API."],
    "securityChanges": ["Move inline DB password to a secret manager."],
    "testingChanges": ["JUnit -> xUnit."],
    "deploymentChanges": ["Reuse the Dockerfile with a .NET SDK image."],
    "observabilityChanges": ["Spring Boot Actuator -> health check middleware."],
    "performanceChanges": ["Connection pooling defaults differ."],
    "risks": [
        {"area": "security", "severity": "red",
         "why": "DB password is hardcoded in application.properties.",
         "whatBreaks": "Credential leak on repo share.",
         "solution": "Move to environment variables / vault.",
         "validation": "Grep the migrated repo for secrets."},
    ],
    "recommendations": ["Externalize secrets first."],
    "migrationPhases": [
        {"name": "Understand application", "description": "Map modules."},
        {"name": "Human approval", "description": "Sign off each change."},
    ],
    "validationStrategy": ["Run converted tests in CI."],
    "rollbackStrategy": ["Keep the Java service deployed behind a flag."],
    "examples": ["@Entity -> [Table] + DbSet<Widget>."],
}

_ANALYZE_BODY = {
    "target_stack": {
        "language": "C#",
        "framework": "ASP.NET Core",
        "runtime": ".NET 8",
        "database": "PostgreSQL",
        "orm": "EF Core",
        "testing": "xUnit",
        "build": "NuGet",
        "deployment": "Docker",
    }
}


def test_analyze_returns_report_plus_deterministic_scores(spring_zip):
    provider = _JsonProvider(json.dumps(REPORT_JSON))
    client = _client(provider)
    project_id = _upload(client, spring_zip).json()["project_id"]
    try:
        resp = client.post("/api/migration/analyze",
                           json={**_ANALYZE_BODY, "project_id": project_id})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["project_id"] == project_id
        assert body["report"]["summary"].startswith("A small Spring Boot")
        assert body["report"]["risks"][0]["severity"] == "red"
        assert len(body["report"]["migrationPhases"]) == 2
        scores = body["readiness"]["scores"]
        assert scores["overall"] == round(
            sum(scores[a] * WEIGHTS[a] for a in AREAS)
        )
        # Deterministic, not from the model: secrets were detected.
        assert any(i["severity"] == "red" and i["area"] == "security"
                   for i in body["readiness"]["issues"])
        assert body["report"]["grounded"] is False  # empty knowledge base
    finally:
        _cleanup(project_id)


def test_analyze_unknown_project_404():
    client = _client(_JsonProvider(json.dumps(REPORT_JSON)))
    resp = client.post("/api/migration/analyze",
                       json={**_ANALYZE_BODY, "project_id": "missing1"})
    assert resp.status_code == 404
