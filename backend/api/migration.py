"""Phase 6 repository analysis API.

POST /api/migration/upload   — ZIP upload -> extracted project + detected stack
GET  /api/migration/{id}     — project summary
POST /api/migration/analyze  — LLM structured migration report (Appendix A)
                                + deterministic readiness scores

Safety: uploads are untrusted. ZIPs are extracted with path-traversal
protection and size caps; only text files are ever read (never executed);
repo content is data — instructions embedded in a repository are never
followed. The original upload is read-only; Phase 7 writes only approved
output to a separate `migrated/` tree.
"""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from analyzers.detect import DetectedStack, detect_project
from analyzers.scoring import Readiness, compute_readiness
from api.compare import TechStack
from domain.schemas import GroundedMixin
from llm.prompts import EQUIVALENCE_GRADES, MIGRATION_REPORT_TEMPLATE, SYSTEM_PROMPT
from llm.provider import AIProvider, get_provider
from llm.structured import StructuredOutputError, generate_json
from rag.embeddings import Embedder, get_embedder
from rag.grounding import citations_for, ground_task
from rag.vector_store import VectorStore, get_vector_store

router = APIRouter()

PROJECTS_DIR = Path(__file__).resolve().parent.parent / "data" / "projects"

MAX_ZIP_BYTES = 50 * 1024 * 1024  # 50 MB upload cap
MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024  # zip-bomb guard
MAX_FILES = 20_000
MAX_INVENTORY = 10_000


# ---------------------------------------------------------------------------
# Report schema (plan Appendix A)
# ---------------------------------------------------------------------------

Equivalence = Literal["exact", "conceptual", "partial", "none"]
RiskSeverity = Literal["red", "yellow", "green"]


class TechMappingRow(BaseModel):
    source: str
    target: str
    equivalence: Equivalence
    notes: str = ""


class RiskItem(BaseModel):
    area: str
    severity: RiskSeverity
    why: str = Field(description="Why this is risky.")
    whatBreaks: str = Field(description="What can break.")
    solution: str = Field(description="Recommended solution.")
    validation: str = Field(description="How to validate the fix.")


class MigrationPhaseItem(BaseModel):
    name: str
    description: str


class MigrationReport(GroundedMixin):
    summary: str
    migrationDifficulty: Literal["Low", "Medium", "High"]
    overallRisk: Literal["Low", "Medium", "High"]
    technologyMapping: list[TechMappingRow] = Field(default_factory=list)
    breakingChanges: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    codeChanges: list[str] = Field(default_factory=list)
    configurationChanges: list[str] = Field(default_factory=list)
    databaseChanges: list[str] = Field(default_factory=list)
    securityChanges: list[str] = Field(default_factory=list)
    testingChanges: list[str] = Field(default_factory=list)
    deploymentChanges: list[str] = Field(default_factory=list)
    observabilityChanges: list[str] = Field(default_factory=list)
    performanceChanges: list[str] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    migrationPhases: list[MigrationPhaseItem] = Field(default_factory=list)
    validationStrategy: list[str] = Field(default_factory=list)
    rollbackStrategy: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class MigrationAnalysis(BaseModel):
    project_id: str
    detected: DetectedStack
    target_stack: TechStack
    readiness: Readiness
    report: MigrationReport


class ProjectSummary(BaseModel):
    project_id: str
    file_count: int
    total_bytes: int
    detected: DetectedStack


class AnalyzeRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=64)
    target_stack: TechStack
    ground: bool = Field(default=True)


# ---------------------------------------------------------------------------
# Project storage
# ---------------------------------------------------------------------------


def _project_dir(project_id: str) -> Path:
    if not project_id or not all(c.isalnum() or c in "-_" for c in project_id):
        raise HTTPException(status_code=400, detail="invalid project id")
    return PROJECTS_DIR / project_id


def _load_project(project_id: str) -> dict:
    meta = _project_dir(project_id) / "project.json"
    if not meta.is_file():
        raise HTTPException(status_code=404, detail="project not found")
    return json.loads(meta.read_text(encoding="utf-8"))


def _save_project(project_id: str, data: dict) -> None:
    d = _project_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "project.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> tuple[int, int]:
    """Extract with zip-slip protection and bomb guards. Returns (files, bytes)."""
    total_uncompressed = sum(i.file_size for i in zf.infolist())
    if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
        raise HTTPException(status_code=413, detail="archive uncompresses too large")
    if len(zf.infolist()) > MAX_FILES:
        raise HTTPException(status_code=413, detail="archive has too many files")

    files = 0
    total_bytes = 0
    for member in zf.infolist():
        name = member.filename
        # Skip directories, absolute paths, and anything escaping dest.
        if name.endswith("/"):
            continue
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts:
            continue
        target = (dest / rel).resolve()
        if not str(target).startswith(str(dest.resolve()) + "/"):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as out:
            while chunk := src.read(1024 * 1024):
                out.write(chunk)
        files += 1
        total_bytes += member.file_size
    return files, total_bytes


@router.post("/migration/upload", response_model=ProjectSummary)
async def upload_project(file: UploadFile = File(...)) -> ProjectSummary:
    filename = (file.filename or "").lower()
    if not filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="only .zip uploads are supported")
    data = await file.read()
    if len(data) > MAX_ZIP_BYTES:
        raise HTTPException(status_code=413, detail="zip exceeds 50 MB")
    if len(data) < 4:
        raise HTTPException(status_code=400, detail="empty upload")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="not a valid zip file")

    project_id = uuid.uuid4().hex[:12]
    src_dir = _project_dir(project_id) / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zf:
            file_count, total_bytes = _safe_extract(zf, src_dir)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"extract failed: {exc}")
    if file_count == 0:
        raise HTTPException(status_code=400, detail="zip contained no files")

    facts = detect_project(src_dir, file_count=file_count, total_bytes=total_bytes)
    _save_project(project_id, {
        "project_id": project_id,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "detected": facts.model_dump(),
    })
    return ProjectSummary(
        project_id=project_id,
        file_count=file_count,
        total_bytes=total_bytes,
        detected=facts,
    )


@router.get("/migration/{project_id}", response_model=ProjectSummary)
async def get_project(project_id: str) -> ProjectSummary:
    data = _load_project(project_id)
    return ProjectSummary(
        project_id=data["project_id"],
        file_count=data["file_count"],
        total_bytes=data["total_bytes"],
        detected=DetectedStack(**data["detected"]),
    )


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _facts_text(facts: DetectedStack) -> str:
    langs = ", ".join(
        f"{l.name}{' ' + l.version if l.version else ''} ({l.files} files)"
        for l in facts.languages
    ) or "(none detected)"
    deps = ", ".join(
        f"{d.name}{('@' + d.version) if d.version else ''}"
        for d in facts.dependencies[:60]
    ) or "(none)"
    lines = [
        f"Languages: {langs}",
        f"Frameworks: {', '.join(facts.frameworks) or '(none)'}",
        f"Build systems: {', '.join(facts.build_systems) or '(none)'}",
        f"Databases: {', '.join(facts.databases) or '(none)'}",
        f"ORMs: {', '.join(facts.orms) or '(none)'}",
        f"Testing: {', '.join(facts.testing_frameworks) or '(none)'}",
        f"Deployment: {', '.join(facts.deployment) or '(none)'}",
        f"CI: {', '.join(facts.ci) or '(none)'}",
        f"Auth hints: {', '.join(facts.auth_hints) or '(none)'}",
        f"Config files: {', '.join(facts.config_files[:12]) or '(none)'}",
        f"Dependencies ({len(facts.dependencies)}): {deps}",
        f"Files: {facts.file_count}, total bytes: {facts.total_bytes}",
    ]
    return "\n".join(lines)


def _target_text(stack: TechStack) -> str:
    return "\n".join(
        f"- {field}: {getattr(stack, field) or '(keep as-is / decide)'}"
        for field in (
            "language", "framework", "runtime", "database", "orm",
            "testing", "build", "deployment",
        )
    )


@router.post("/migration/analyze", response_model=MigrationAnalysis)
async def analyze_migration(
    req: AnalyzeRequest,
    provider: AIProvider = Depends(get_provider),
    embedder: Embedder = Depends(get_embedder),
    store: VectorStore = Depends(get_vector_store),
) -> MigrationAnalysis:
    data = _load_project(req.project_id)
    facts = DetectedStack(**data["detected"])
    readiness = compute_readiness(facts)

    scores_text = "\n".join(
        f"- {area}: {score}%" for area, score in readiness.scores.items()
    )
    task = MIGRATION_REPORT_TEMPLATE.format(
        facts=_facts_text(facts),
        target_stack=_target_text(req.target_stack),
        scores=scores_text,
        EQUIVALENCE_GRADES=EQUIVALENCE_GRADES,
    )
    # Ground the report in the target stack's official docs.
    grounding_block, chunks = await ground_task(
        query=(
            f"Migrate {', '.join(l.name for l in facts.languages) or 'application'} "
            f"({', '.join(facts.frameworks) or 'no framework'}) to "
            f"{req.target_stack.language} {req.target_stack.framework}"
        ).strip(),
        tech=req.target_stack.language or "general",
        version=req.target_stack.runtime or None,
        ground=req.ground,
        embedder=embedder,
        store=store,
    )
    task += grounding_block
    try:
        report = await generate_json(provider, SYSTEM_PROMPT, task, MigrationReport)
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "raw": exc.raw_text[:4000]},
        )
    report.grounded = bool(chunks)
    if not report.sources:
        report.sources = citations_for(chunks)
    return MigrationAnalysis(
        project_id=req.project_id,
        detected=facts,
        target_stack=req.target_stack,
        readiness=readiness,
        report=report,
    )
