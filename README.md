# Tech Migration AI — Phase 1: Basic AI Chat

An AI migration and learning companion that understands what you already know.
Phase 1 ships a streaming chat UI: Next.js → FastAPI → local Ollama LLM.

**Stack:** Next.js + TypeScript · Python + FastAPI · Ollama (local, free) ·
Postgres + Qdrant (defined, idle until later phases) · Docker Compose.

## Step-by-step: run Phase 1

### 1. Install prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for the stack)
- [Ollama](https://ollama.com/download) (for the free local LLM)

### 2. Pull a coding-capable model
```bash
ollama pull qwen2.5-coder:14b
```
Any Ollama model works — the name is just config (`OLLAMA_MODEL`). A 7B model
(e.g. `qwen2.5-coder:7b`) runs on 16 GB RAM if the 14B is too heavy.

### 3. Start everything
```bash
cp .env.example .env        # optional: adjust model name / URLs
docker compose up --build
```
- Chat UI: http://localhost:3000
- API health: http://localhost:8000/api/health
- OpenAPI docs: http://localhost:8000/docs

> Keep `ollama serve` running on the host. Inside Docker the backend reaches it
> at `http://host.docker.internal:11434` (the compose default).

### 4. Run the acceptance check
In the chat UI, ask:

> **Explain Java streams to me as a C# developer.**

You should see a streamed answer that compares the Java concept with C# LINQ,
shows code in both languages, and names the differences. If Ollama is stopped,
the UI shows an amber "model unavailable" badge instead of hanging — start
Ollama and retry.

### 5. (Dev) Run without Docker
```bash
# backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload          # http://localhost:8000

# frontend (new terminal)
cd frontend && npm install && npm run dev   # http://localhost:3000
```

## Tests

Backend tests mock the LLM — no Ollama needed:
```bash
cd backend && source .venv/bin/activate && pytest
```
Covers: provider contract (token order, system prompt, ping true/false),
factory defaults and invalid config, chat SSE streaming, error events,
request validation, and `/api/health`.

Frontend: `npm run build` (type-check + production build) must pass.

## Switch providers later

```bash
AI_PROVIDER=openai OPENAI_API_KEY=sk-... uvicorn main:app
```
The `AIProvider` interface is the seam: add new providers in
`backend/llm/provider.py` without touching business logic. `OpenAIProvider`
is currently a stub that raises until keys are configured.

## What's coming in Phase 2

Technology comparison: source/target pickers, concept-by-concept comparison,
graded mapping tables (exact / similar / partial / none) driven by YAML data.
Then: code conversion (Phase 3), personalized learning (Phase 4), RAG over
official docs (Phase 5), repository analysis (Phase 6), automated migration
with human approval (Phase 7).

See the full plan: `~/workspace/your_files/tech-migration-ai-plan/tech-migration-ai-plan.pdf`.
