"""Phase 3 code conversion API: original / direct / idiomatic / modern
four-block conversion plus a structured explanation.

Output goes through the same Pydantic-validated JSON pipeline as Phase 2:
the model is asked for JSON only, validated, retried once on failure, and a
persistent failure becomes HTTP 502 with the raw text attached — never
fabricated data.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from llm.prompts import CODE_CONVERT_TEMPLATE, EQUIVALENCE_GRADES, SYSTEM_PROMPT
from llm.provider import AIProvider, get_provider
from llm.structured import StructuredOutputError, generate_json

router = APIRouter()

Equivalence = Literal["exact", "conceptual", "partial", "none"]


class ConvertRequest(BaseModel):
    source_tech: str = Field(min_length=1, max_length=80)
    source_version: Optional[str] = Field(default=None, max_length=40)
    target_tech: str = Field(min_length=1, max_length=80)
    target_version: Optional[str] = Field(default=None, max_length=40)
    source_code: str = Field(min_length=1, max_length=12000)
    style_hint: Optional[str] = Field(
        default=None,
        max_length=80,
        description="Optional context such as 'spring-controller' or 'junit-test'.",
    )


class ConversionExplanation(BaseModel):
    what_changed: list[str] = Field(min_length=1)
    why_changed: list[str] = Field(min_length=1)
    target_differences: str
    new_capabilities: list[str] = Field(default_factory=list)
    performance_notes: str = ""
    common_mistakes: list[str] = Field(default_factory=list)
    modern_note: str = Field(
        default="",
        description="One sentence explaining why modern_target matches idiomatic_target, or empty.",
    )


class CodeConversion(BaseModel):
    source_code: str
    direct_translation: str
    idiomatic_target: str
    modern_target: str
    equivalence: Equivalence
    explanation: ConversionExplanation


def _ver(v: Optional[str]) -> str:
    return f" ({v})" if v else ""


@router.post("/convert", response_model=CodeConversion)
async def convert_code(
    req: ConvertRequest, provider: AIProvider = Depends(get_provider)
) -> CodeConversion:
    style_hint_line = (
        f"Style hint (the code is a {req.style_hint}; honor its conventions): {req.style_hint}"
        if req.style_hint
        else "Style hint: none."
    )
    task = CODE_CONVERT_TEMPLATE.format(
        source_tech=req.source_tech,
        source_version=_ver(req.source_version),
        target_tech=req.target_tech,
        target_version=_ver(req.target_version),
        style_hint_line=style_hint_line,
        source_code=req.source_code,
        EQUIVALENCE_GRADES=EQUIVALENCE_GRADES,
    )
    try:
        return await generate_json(provider, SYSTEM_PROMPT, task, CodeConversion)
    except StructuredOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail={"error": str(exc), "raw": exc.raw_text[:4000]},
        )
