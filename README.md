# Tech Migration AI — Phase 2: Technology Comparison

An AI migration and learning companion that understands what you already know.
Phase 1 shipped a streaming chat UI (Next.js → FastAPI → local Ollama LLM).
Phase 2 adds structured technology comparison: a `/compare` page with
concept-by-concept comparison, graded stack mapping, and side-by-side code
comparison — all LLM-backed but Pydantic-validated, never free-form prose.

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

## Phase 2: compare technologies

Open http://localhost:3000/compare (top nav: 🔀 Compare). Three sections:

1. **Concept comparison** — pick source/target tech + version from the
   catalog (or type anything free-text via "Other…"), enter a concept like
   `CompletableFuture`, and get a structured comparison: source/target code,
   key difference, target advantage, common migration problem, recommended
   approach — plus an honestly-graded equivalence badge (exact / conceptual /
   partial / none). Try: `Java 17 → C# (.NET 8)`, concept `CompletableFuture`.
2. **Stack mapping** — fill in source and target stacks (language, framework,
   runtime, database, ORM, testing, build, deployment) and get a graded
   row-by-row mapping table. Try: Spring Boot stack → .NET 8 stack.
3. **Code compare** — paste source code, get the closest equivalent target
   implementation side by side with the differences that matter. (The full
   four-block conversion — original / direct / idiomatic / modern — ships in
   Phase 3.)

API (validated JSON everywhere):
- `GET /api/tech/catalog` — technology catalog (languages, runtimes,
  frameworks, ORMs, databases, testing, build, deployment with real versions).
- `POST /api/compare/concept` — `{source_tech, source_version?, target_tech,
  target_version?, concept}` → graded `ConceptComparison`.
- `POST /api/compare/mapping` — `{source_stack, target_stack}` → rows of
  `{source, target, equivalence, note}`.
- `POST /api/compare/code` — `{source_tech, target_tech, source_code}` →
  `{source_code, target_code, notes}`.

The prompt enforces honest equivalence labeling (`exact` is rare; the model
must say `conceptual`/`partial`/`none` when in doubt and never invent APIs).
The server asks the LLM for JSON only, validates with Pydantic, retries once
on failure, and returns HTTP 502 with the raw text attached if it still
fails — never fabricated data. See `backend/llm/structured.py` and
`backend/llm/prompts.py`.

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
request validation, `/api/health`, comparison endpoints (validated JSON
schema, retry-once path, 502-with-raw path on persistent failure, 422s),
and the tech catalog contents.

Frontend: `npm run build` (type-check + production build) must pass.

## Switch providers later

```bash
AI_PROVIDER=openai OPENAI_API_KEY=sk-... uvicorn main:app
```
The `AIProvider` interface is the seam: add new providers in
`backend/llm/provider.py` without touching business logic. `OpenAIProvider`
is currently a stub that raises until keys are configured.

## What's coming next

Phase 3 — code conversion: paste code, pick a pair, get the four-block
conversion (original / direct / idiomatic / modern) plus explanation.
Then: personalized learning (Phase 4), RAG over official docs (Phase 5),
repository analysis (Phase 6), automated migration with human approval
(Phase 7).

See the full plan: `~/workspace/your_files/tech-migration-ai-plan/tech-migration-ai-plan.pdf`.
