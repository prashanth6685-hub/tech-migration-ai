"""Shared Pydantic contracts used across API modules.

Citation carries RAG grounding: which official documentation a response drew
on. `grounded` is set server-side — True only when retrieval actually found
chunks for the request. The UI renders a badge from it.
"""
from pydantic import BaseModel, Field


class Citation(BaseModel):
    title: str = Field(description="Document title of the retrieved chunk.")
    url: str = Field(
        default="",
        description="Source URL, copied exactly from the chunk ('' for pasted docs).",
    )


class GroundedMixin(BaseModel):
    """Mixin for AI responses that can be grounded in retrieved docs."""

    sources: list[Citation] = Field(
        default_factory=list,
        description=(
            "Official documentation the answer drew on. Copy title and URL "
            "EXACTLY from the retrieved chunks below — never invent URLs. "
            "Leave empty when no chunk was relevant."
        ),
    )
    grounded: bool = Field(
        default=False,
        description="Server-set: True only when retrieval returned chunks.",
    )
