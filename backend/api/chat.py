"""Phase 1 chat API: SSE-streamed chat backed by the configured AIProvider."""
import json
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from llm.prompts import SYSTEM_PROMPT
from llm.provider import AIProvider, get_provider

router = APIRouter()


class ChatMessage(BaseModel):
    role: str = Field(pattern="^(user|assistant|system)$")
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    system: Optional[str] = Field(
        default=None,
        description="Optional system-prompt override. Defaults to the architect persona.",
    )


class HealthResponse(BaseModel):
    status: str
    provider: str
    model: str
    ollama_reachable: bool


@router.post("/chat")
async def chat(req: ChatRequest, provider: AIProvider = Depends(get_provider)):
    """Stream the assistant answer as Server-Sent Events.

    Events are `data: <json>` lines: {"token": "..."} chunks, a final
    {"done": true}, or {"error": "..."} when the provider fails.
    """
    system = req.system or SYSTEM_PROMPT
    messages = [m.model_dump() for m in req.messages]

    async def event_gen():
        try:
            async for token in provider.chat_stream(messages, system=system):
                yield f"data: {json.dumps({'token': token})}\n\n"
        except Exception as exc:  # never leave the stream hanging
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/health", response_model=HealthResponse)
async def health(provider: AIProvider = Depends(get_provider)):
    return HealthResponse(
        status="ok",
        provider=provider.name,
        model=provider.model,
        ollama_reachable=await provider.ping(),
    )
