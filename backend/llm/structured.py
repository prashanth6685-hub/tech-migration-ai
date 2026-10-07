"""Structured JSON generation over the AIProvider.

Every AI-backed comparison endpoint asks the model for JSON only, validates
it against a Pydantic model, retries once with the validation error appended,
and raises StructuredOutputError (surfaced as HTTP 502 with the raw text
attached) when it still fails. We never fabricate structured data.
"""
from __future__ import annotations

import json
import re
from typing import Type, TypeVar

from pydantic import BaseModel, ValidationError

from llm.provider import AIProvider

T = TypeVar("T", bound=BaseModel)

JSON_ONLY_SUFFIX = """
Respond with a single JSON object and nothing else. No markdown fences,
no commentary, no trailing text. The JSON must conform to this schema:

{schema}
"""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class StructuredOutputError(Exception):
    """The model did not produce valid JSON after a retry.

    Carries the raw text so the API can return it for debugging —
    never silently invented data.
    """

    def __init__(self, message: str, raw_text: str) -> None:
        super().__init__(message)
        self.raw_text = raw_text


def extract_json(text: str) -> object:
    """Pull the first JSON object out of model output.

    Handles fenced code blocks and prose around the object. Raises
    json.JSONDecodeError when no parseable object is found.
    """
    stripped = text.strip()
    fence = _FENCE_RE.search(stripped)
    if fence:
        stripped = fence.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    # Fall back to the widest {...} span in the text.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return json.loads(stripped[start : end + 1])
    raise json.JSONDecodeError("no JSON object found", stripped, 0)


async def _collect_text(
    provider: AIProvider, system: str, messages: list[dict[str, str]]
) -> str:
    parts: list[str] = []
    async for token in provider.chat_stream(messages, system=system):
        parts.append(token)
    return "".join(parts)


async def generate_json(
    provider: AIProvider,
    system: str,
    task_prompt: str,
    model_class: Type[T],
    max_retries: int = 1,
) -> T:
    """Ask the model for JSON conforming to `model_class` and validate it.

    Retries once with the validation error appended so the model can fix
    its output; raises StructuredOutputError on persistent failure.
    """
    schema = json.dumps(model_class.model_json_schema(), indent=2)
    messages: list[dict[str, str]] = [
        {"role": "user", "content": task_prompt + JSON_ONLY_SUFFIX.format(schema=schema)}
    ]

    raw_text = ""
    last_error: Exception | None = None
    for _ in range(max_retries + 1):
        raw_text = await _collect_text(provider, system, messages)
        try:
            data = extract_json(raw_text)
            return model_class.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            messages.append({"role": "assistant", "content": raw_text})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous response failed validation:\n"
                        f"{exc}\n"
                        "Fix it and respond with JSON only, conforming to the schema."
                    ),
                }
            )

    raise StructuredOutputError(
        f"Model did not return valid JSON after {max_retries + 1} attempt(s): {last_error}",
        raw_text,
    )
