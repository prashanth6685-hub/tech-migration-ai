"""Deterministic migration readiness scoring (Phase 6).

Scores come from analyzer findings — pure functions, no LLM. The model
explains the scores in the report; it never invents the numbers.

Areas and weights (sum to 1.0):
  code .20, dependencies .20, database .15, security .15,
  testing .10, deployment .10, configuration .10
"""
from pydantic import BaseModel, Field

from analyzers.detect import DetectedStack

AREAS = (
    "code",
    "dependencies",
    "database",
    "security",
    "testing",
    "deployment",
    "configuration",
)

WEIGHTS = {
    "code": 0.20,
    "dependencies": 0.20,
    "database": 0.15,
    "security": 0.15,
    "testing": 0.10,
    "deployment": 0.10,
    "configuration": 0.10,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "readiness weights must sum to 1"


class ReadinessIssue(BaseModel):
    severity: str = Field(pattern="^(red|yellow|green)$")
    area: str
    title: str
    detail: str


class Readiness(BaseModel):
    scores: dict[str, int]  # overall + one per area, 0-100
    issues: list[ReadinessIssue]


def _base_scores(facts: DetectedStack) -> dict[str, int]:
    """Starting score per area before findings deduct."""
    return {
        "code": 100,
        "dependencies": 100,
        # ORM-backed data layers migrate cleaner than raw SQL.
        "database": 90 if facts.orms else (75 if facts.databases else 60),
        "security": 80,
        # Tests present but framework unknown is better than none at all.
        "testing": 90
        if (facts.testing_frameworks and _has_tests(facts))
        else (60 if _has_tests(facts) else 40),
        "deployment": 45,
        "configuration": 90 if facts.config_files else 70,
    }


def _has_tests(facts: DetectedStack) -> bool:
    return any(
        f.area == "testing" and f.severity == "green" for f in facts.findings
    )


def compute_readiness(facts: DetectedStack) -> Readiness:
    scores = _base_scores(facts)

    # Deployment starts low and earns points for automation signals.
    if "Docker" in facts.deployment:
        scores["deployment"] = max(scores["deployment"], 90)
    elif facts.ci:
        scores["deployment"] = max(scores["deployment"], 75)
    if "Kubernetes" in facts.deployment:
        scores["deployment"] = min(95, scores["deployment"] + 5)

    issues: list[ReadinessIssue] = []
    for f in facts.findings:
        if f.area in scores:
            scores[f.area] = max(0, scores[f.area] - f.deduction)
        issues.append(
            ReadinessIssue(
                severity=f.severity, area=f.area, title=f.title, detail=f.detail
            )
        )

    # Deterministic ordering: red first, then yellow, then green; by area.
    rank = {"red": 0, "yellow": 1, "green": 2}
    issues.sort(key=lambda i: (rank[i.severity], i.area, i.title))

    overall = round(sum(scores[a] * WEIGHTS[a] for a in AREAS))
    return Readiness(scores={"overall": overall, **scores}, issues=issues)
