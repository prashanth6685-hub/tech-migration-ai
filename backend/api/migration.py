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
import re
import uuid
import zipfile
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from analyzers.detect import EXT_LANGUAGE, DetectedStack, detect_project
from analyzers.scoring import Readiness, compute_readiness
from api.compare import TechStack
from api.convert import CodeConversion
from domain.schemas import GroundedMixin
from llm.prompts import (
    CODE_CONVERT_TEMPLATE,
    EQUIVALENCE_GRADES,
    MIGRATION_REPORT_TEMPLATE,
    SYSTEM_PROMPT,
    TEST_GENERATE_TEMPLATE,
)
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
    # Persist the target stack — Phase 7 file conversion uses it.
    data["target_stack"] = req.target_stack.model_dump()
    _save_project(req.project_id, data)
    return MigrationAnalysis(
        project_id=req.project_id,
        detected=facts,
        target_stack=req.target_stack,
        readiness=readiness,
        report=report,
    )


# ---------------------------------------------------------------------------
# Phase 7 — Automated migration with human approval
#
# Nothing is ever applied destructively: the uploaded source tree is
# read-only; only APPROVED output is written, and only into the separate
# `migrated/<project_id>/` tree. The approval queue is permanent.
# ---------------------------------------------------------------------------

CONVERTIBLE_EXTS = set(EXT_LANGUAGE.keys())
MAX_CONVERT_BYTES = 100_000  # files larger than this are not offered
FileStatus = Literal["untouched", "pending", "approved", "rejected"]
ChangeRisk = Literal["low", "medium", "high"]

_TEST_EXT = {
    "C#": ".cs",
    "Java": ".java",
    "Python": ".py",
    "TypeScript": ".ts",
    "JavaScript": ".js",
    "Go": ".go",
    "Kotlin": ".kt",
    "Rust": ".rs",
}
_TEST_FRAMEWORK_DEFAULT = {
    "C#": "xUnit",
    "Java": "JUnit",
    "Python": "pytest",
    "TypeScript": "vitest",
    "JavaScript": "vitest",
    "Go": "testing",
    "Kotlin": "JUnit",
}


class ProjectFile(BaseModel):
    path: str
    size: int
    language: str
    status: FileStatus


class ConvertFileRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=500)
    ground: bool = Field(default=True)


class FileConversion(BaseModel):
    path: str
    kind: Literal["conversion"] = "conversion"
    status: FileStatus
    original: str
    proposed: str
    explanation: str
    equivalence: Equivalence
    risk: ChangeRisk
    risk_why: str
    warnings: list[str] = Field(
        description="Heuristic static checks (NOT a compiler): unbalanced "
        "brackets, ... placeholders, TODO stubs."
    )


class TestFileContent(BaseModel):
    test_code: str
    framework: str
    notes: str = ""


class GenerateTestsRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=500, description="Source file path.")


class GeneratedTests(BaseModel):
    path: str = Field(description="Output test file path (change key).")
    kind: Literal["test"] = "test"
    status: FileStatus
    source_path: str
    test_code: str
    framework: str
    notes: str
    warnings: list[str] = Field(description="Heuristic static checks, not a compiler.")


class ApproveRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=64)
    path: str = Field(min_length=1, max_length=500, description="Change key.")
    approved: bool
    note: Optional[str] = Field(default=None, max_length=500)


def _safe_relpath(raw: str) -> str:
    """Validate a user-supplied relative path (zip-slip style guard)."""
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts or not raw.strip():
        raise HTTPException(status_code=400, detail="invalid path")
    return str(rel)


def _src_file(project_id: str, relpath: str) -> Path:
    rel = _safe_relpath(relpath)
    src_dir = (_project_dir(project_id) / "src").resolve()
    target = (src_dir / rel).resolve()
    if not str(target).startswith(str(src_dir) + "/") or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found in project")
    return target


def _heuristic_warnings(code: str) -> list[str]:
    """Lightweight static checks on generated code.

    These are HEURISTICS, not a compiler: they catch obvious problems
    (placeholders, unbalanced brackets) but prove nothing about correctness.
    """
    warnings: list[str] = []
    if not code.strip():
        warnings.append("proposed code is empty")
        return warnings
    for open_c, close_c, name in (("{", "}", "braces"), ("(", ")", "parentheses"), ("[", "]", "brackets")):
        if code.count(open_c) != code.count(close_c):
            warnings.append(
                f"unbalanced {name} ({code.count(open_c)} vs {code.count(close_c)})"
            )
    if re.search(r"\.\.\.", code):
        warnings.append("possible '...' placeholder in generated code")
    if re.search(r"(?i)rest of (the )?code", code):
        warnings.append("possible 'rest of code' placeholder")
    if "TODO" in code and len(code) < 800:
        warnings.append("TODO stub without a full implementation")
    return warnings


def _assess_risk(relpath: str, original: str, equivalence: Equivalence,
                 warnings: list[str]) -> tuple[ChangeRisk, str]:
    reasons: list[str] = []
    risk: ChangeRisk = "low"
    low = relpath.lower()
    if any(k in low for k in ("auth", "security", "crypto", "password", "secret", "token")):
        risk, reasons = "high", ["security-sensitive file"]
    if equivalence == "none":
        risk = "high"
        reasons.append("no direct equivalent — the conversion is a redesign")
    elif equivalence == "partial" and risk != "high":
        risk, reasons = "medium", reasons + ["partial equivalence — review semantics"]
    if any("placeholder" in w for w in warnings):
        risk = "high"
        reasons.append("generated code may contain placeholders")
    lines = original.count("\n") + 1
    if lines > 500 and risk == "low":
        risk, reasons = "medium", reasons + [f"large file ({lines} lines)"]
    if not reasons:
        reasons = ["straightforward conversion, no red flags from heuristics"]
    return risk, "; ".join(reasons)


def _target_of(data: dict) -> TechStack:
    ts = data.get("target_stack")
    if not ts:
        raise HTTPException(
            status_code=400, detail="run migration analysis first (no target stack)"
        )
    return TechStack(**ts)


@router.get("/migration/{project_id}/files", response_model=list[ProjectFile])
async def list_project_files(project_id: str) -> list[ProjectFile]:
    data = _load_project(project_id)
    src_dir = _project_dir(project_id) / "src"
    changes: dict = data.get("changes", {})
    out: list[ProjectFile] = []
    for p in sorted(src_dir.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in CONVERTIBLE_EXTS:
            continue
        size = p.stat().st_size
        if size > MAX_CONVERT_BYTES:
            continue
        rel = str(p.relative_to(src_dir))
        status = changes.get(rel, {}).get("status", "untouched")
        out.append(
            ProjectFile(
                path=rel,
                size=size,
                language=EXT_LANGUAGE.get(p.suffix.lower(), p.suffix),
                status=status,
            )
        )
    return out


async def _run_code_conversion(
    provider: AIProvider,
    facts: DetectedStack,
    target: TechStack,
    original: str,
    ground: bool,
    embedder: Embedder,
    store: VectorStore,
) -> CodeConversion:
    source_tech = facts.languages[0].name if facts.languages else "unknown"
    source_ver = facts.languages[0].version if facts.languages else ""
    task = CODE_CONVERT_TEMPLATE.format(
        source_tech=source_tech,
        source_version=f" ({source_ver})" if source_ver else "",
        target_tech=target.language or "unknown",
        target_version=f" ({target.runtime})" if target.runtime else "",
        style_hint_line="Style hint: none.",
        source_code=original,
        EQUIVALENCE_GRADES=EQUIVALENCE_GRADES,
    )
    grounding_block, chunks = await ground_task(
        query=f"Convert {source_tech} to {target.language} {target.runtime or ''}: "
        f"{original[:400]}".strip(),
        tech=target.language or "general",
        version=target.runtime or None,
        ground=ground,
        embedder=embedder,
        store=store,
    )
    task += grounding_block
    try:
        return await generate_json(provider, SYSTEM_PROMPT, task, CodeConversion)
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "raw": exc.raw_text[:4000]},
        )


@router.post("/migration/convert-file", response_model=FileConversion)
async def convert_project_file(
    req: ConvertFileRequest,
    provider: AIProvider = Depends(get_provider),
    embedder: Embedder = Depends(get_embedder),
    store: VectorStore = Depends(get_vector_store),
) -> FileConversion:
    data = _load_project(req.project_id)
    src = _src_file(req.project_id, req.path)
    if src.suffix.lower() not in CONVERTIBLE_EXTS:
        raise HTTPException(status_code=400, detail="file type is not convertible")
    if src.stat().st_size > MAX_CONVERT_BYTES:
        raise HTTPException(status_code=400, detail="file too large to convert")
    target = _target_of(data)
    facts = DetectedStack(**data["detected"])
    rel = _safe_relpath(req.path)

    # Idempotent: a previous conversion is returned as-is (no repeat LLM call).
    changes: dict = data.setdefault("changes", {})
    if rel in changes and changes[rel].get("kind", "conversion") == "conversion":
        rec = changes[rel]
        return FileConversion(
            path=rel,
            status=rec["status"],
            original=src.read_text(encoding="utf-8", errors="replace"),
            proposed=rec["proposed"],
            explanation=rec["explanation"],
            equivalence=rec["equivalence"],
            risk=rec["risk"],
            risk_why=rec["risk_why"],
            warnings=rec["warnings"],
        )

    original = src.read_text(encoding="utf-8", errors="replace")
    conv = await _run_code_conversion(
        provider, facts, target, original, req.ground, embedder, store
    )
    warnings = _heuristic_warnings(conv.idiomatic_target)
    risk, risk_why = _assess_risk(rel, original, conv.equivalence, warnings)
    explanation = "; ".join(conv.explanation.what_changed[:5]) or "See full conversion."
    changes[rel] = {
        "kind": "conversion",
        "status": "pending",
        "proposed": conv.idiomatic_target,
        "direct": conv.direct_translation,
        "modern": conv.modern_target,
        "explanation": explanation,
        "full_explanation": conv.explanation.model_dump(),
        "equivalence": conv.equivalence,
        "risk": risk,
        "risk_why": risk_why,
        "warnings": warnings,
    }
    _save_project(req.project_id, data)
    return FileConversion(
        path=rel,
        status="pending",
        original=original,
        proposed=conv.idiomatic_target,
        explanation=explanation,
        equivalence=conv.equivalence,
        risk=risk,
        risk_why=risk_why,
        warnings=warnings,
    )


def _test_framework_for(target: TechStack) -> str:
    if target.testing:
        return target.testing
    return _TEST_FRAMEWORK_DEFAULT.get(target.language, "xUnit")


def _test_output_path(source_rel: str, target: TechStack) -> str:
    stem = Path(source_rel).stem
    ext = _TEST_EXT.get(target.language, ".txt")
    return f"tests/{stem}_test{ext}"


@router.post("/migration/generate-tests", response_model=GeneratedTests)
async def generate_file_tests(
    req: GenerateTestsRequest,
    provider: AIProvider = Depends(get_provider),
    embedder: Embedder = Depends(get_embedder),
    store: VectorStore = Depends(get_vector_store),
) -> GeneratedTests:
    data = _load_project(req.project_id)
    src = _src_file(req.project_id, req.path)
    target = _target_of(data)
    facts = DetectedStack(**data["detected"])
    rel = _safe_relpath(req.path)
    source_tech = facts.languages[0].name if facts.languages else "unknown"
    original = src.read_text(encoding="utf-8", errors="replace")

    changes: dict = data.setdefault("changes", {})
    out_path = _test_output_path(rel, target)
    if out_path in changes:  # idempotent
        rec = changes[out_path]
        return GeneratedTests(
            path=out_path,
            status=rec["status"],
            source_path=rel,
            test_code=rec["test_code"],
            framework=rec["framework"],
            notes=rec["notes"],
            warnings=rec["warnings"],
        )

    proposed = changes.get(rel, {}).get("proposed", "")
    framework = _test_framework_for(target)
    task = TEST_GENERATE_TEMPLATE.format(
        target_tech=target.language or "unknown",
        target_version=f" ({target.runtime})" if target.runtime else "",
        framework=framework,
        source_tech=source_tech,
        original=original[:6000],
        proposed=(proposed or "(no conversion yet — test the source behavior)")[:6000],
    )
    try:
        result = await generate_json(provider, SYSTEM_PROMPT, task, TestFileContent)
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "raw": exc.raw_text[:4000]},
        )
    warnings = _heuristic_warnings(result.test_code)
    changes[out_path] = {
        "kind": "test",
        "source_path": rel,
        "status": "pending",
        "test_code": result.test_code,
        "framework": result.framework or framework,
        "notes": result.notes,
        "warnings": warnings,
    }
    _save_project(req.project_id, data)
    return GeneratedTests(
        path=out_path,
        status="pending",
        source_path=rel,
        test_code=result.test_code,
        framework=result.framework or framework,
        notes=result.notes,
        warnings=warnings,
    )


@router.post("/migration/approve")
async def approve_change(req: ApproveRequest) -> dict:
    data = _load_project(req.project_id)
    changes: dict = data.get("changes", {})
    key = _safe_relpath(req.path)
    rec = changes.get(key)
    if not rec:
        raise HTTPException(
            status_code=400, detail="convert or generate the file first"
        )
    rec["status"] = "approved" if req.approved else "rejected"
    if req.note:
        rec["note"] = req.note
    if req.approved:
        # Approved output goes ONLY to the migrated/ tree — the uploaded
        # source is never modified.
        content = rec.get("proposed") or rec.get("test_code") or ""
        dest = (_project_dir(req.project_id) / "migrated" / key).resolve()
        base = (_project_dir(req.project_id) / "migrated").resolve()
        if not str(dest).startswith(str(base) + "/"):
            raise HTTPException(status_code=400, detail="invalid path")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    else:
        # Rejected: make sure a previously approved version is removed.
        doomed = (_project_dir(req.project_id) / "migrated" / key).resolve()
        if doomed.is_file():
            doomed.unlink()
    _save_project(req.project_id, data)
    return {"path": key, "status": rec["status"]}


@router.get("/migration/{project_id}/download")
async def download_migrated(project_id: str):
    migrated = _project_dir(project_id) / "migrated"
    _load_project(project_id)  # 404 when unknown
    files = (
        [p for p in sorted(migrated.rglob("*")) if p.is_file()]
        if migrated.is_dir()
        else []
    )
    if not files:
        raise HTTPException(status_code=404, detail="no approved files yet")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, p.relative_to(migrated))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=migrated-{project_id}.zip"
        },
    )
