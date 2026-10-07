"""Phase 2 technology comparison API: graded concept comparison, stack
mapping, and light side-by-side code comparison.

All LLM-backed endpoints return Pydantic-validated JSON. The model is asked
for JSON only; output is validated, retried once on failure, and a persistent
failure becomes HTTP 502 with the raw text attached — never fabricated data.
The full four-block conversion (original/direct/idiomatic/modern) is Phase 3.
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from llm.prompts import (
    CODE_COMPARE_TEMPLATE,
    CONCEPT_COMPARE_TEMPLATE,
    EQUIVALENCE_GRADES,
    STACK_MAPPING_TEMPLATE,
    SYSTEM_PROMPT,
)
from llm.provider import AIProvider, get_provider
from llm.structured import StructuredOutputError, generate_json

router = APIRouter()

Equivalence = Literal["exact", "conceptual", "partial", "none"]

_TECH_FIELDS = ("language", "framework", "runtime", "database", "orm", "testing", "build", "deployment")


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _catalog() -> dict:
    path = Path(__file__).resolve().parent.parent / "data" / "tech_catalog.json"
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/tech/catalog")
async def tech_catalog() -> dict:
    """The technology catalog: languages, frameworks, runtimes/versions,
    databases, ORMs, testing frameworks, build systems, deployment platforms."""
    return _catalog()


# ---------------------------------------------------------------------------
# Concept comparison
# ---------------------------------------------------------------------------


class ConceptCompareRequest(BaseModel):
    source_tech: str = Field(min_length=1, max_length=80)
    source_version: Optional[str] = Field(default=None, max_length=40)
    target_tech: str = Field(min_length=1, max_length=80)
    target_version: Optional[str] = Field(default=None, max_length=40)
    concept: str = Field(min_length=1, max_length=200)


class ConceptComparison(BaseModel):
    source_technology: str
    target_technology: str
    concept: str
    equivalence: Equivalence
    source_implementation: str
    target_implementation: str
    key_difference: str
    target_specific_improvement: str = ""
    common_migration_problem: str = ""
    recommended_approach: str


def _ver(v: Optional[str]) -> str:
    return f" ({v})" if v else ""


@router.post("/compare/concept", response_model=ConceptComparison)
async def compare_concept(
    req: ConceptCompareRequest, provider: AIProvider = Depends(get_provider)
) -> ConceptComparison:
    task = CONCEPT_COMPARE_TEMPLATE.format(
        source_tech=req.source_tech,
        source_version=_ver(req.source_version),
        target_tech=req.target_tech,
        target_version=_ver(req.target_version),
        concept=req.concept,
        EQUIVALENCE_GRADES=EQUIVALENCE_GRADES,  # grades ship inside the template already
    )
    try:
        return await generate_json(provider, SYSTEM_PROMPT, task, ConceptComparison)
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "raw": exc.raw_text[:4000]},
        )


# ---------------------------------------------------------------------------
# Stack mapping
# ---------------------------------------------------------------------------


class TechStack(BaseModel):
    language: str = Field(default="", max_length=80)
    framework: str = Field(default="", max_length=80)
    runtime: str = Field(default="", max_length=80)
    database: str = Field(default="", max_length=80)
    orm: str = Field(default="", max_length=80)
    testing: str = Field(default="", max_length=80)
    build: str = Field(default="", max_length=80)
    deployment: str = Field(default="", max_length=80)


class StackMappingRequest(BaseModel):
    source_stack: TechStack
    target_stack: TechStack


class MappingRow(BaseModel):
    source: str
    target: str
    equivalence: Equivalence
    note: str


class StackMapping(BaseModel):
    rows: list[MappingRow] = Field(min_length=1)


def _stack_lines(stack: TechStack) -> str:
    return "\n".join(
        f"- {field}: {getattr(stack, field) or '(none)'}"
        for field in _TECH_FIELDS
        if getattr(stack, field)
    )


@router.post("/compare/mapping", response_model=StackMapping)
async def compare_mapping(
    req: StackMappingRequest, provider: AIProvider = Depends(get_provider)
) -> StackMapping:
    task = STACK_MAPPING_TEMPLATE.format(
        source_stack=_stack_lines(req.source_stack) or "(empty)",
        target_stack=_stack_lines(req.target_stack) or "(empty)",
        EQUIVALENCE_GRADES=EQUIVALENCE_GRADES,
    )
    try:
        return await generate_json(provider, SYSTEM_PROMPT, task, StackMapping)
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "raw": exc.raw_text[:4000]},
        )


# ---------------------------------------------------------------------------
# Light code comparison (Phase 3 adds the full 4-block conversion)
# ---------------------------------------------------------------------------


class CodeCompareRequest(BaseModel):
    source_tech: str = Field(min_length=1, max_length=80)
    target_tech: str = Field(min_length=1, max_length=80)
    source_code: str = Field(min_length=1, max_length=12000)


class CodeComparison(BaseModel):
    source_code: str
    target_code: str
    notes: list[str]


@router.post("/compare/code", response_model=CodeComparison)
async def compare_code(
    req: CodeCompareRequest, provider: AIProvider = Depends(get_provider)
) -> CodeComparison:
    task = CODE_COMPARE_TEMPLATE.format(
        source_tech=req.source_tech,
        target_tech=req.target_tech,
        source_code=req.source_code,
    )
    try:
        return await generate_json(provider, SYSTEM_PROMPT, task, CodeComparison)
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "raw": exc.raw_text[:4000]},
        )
