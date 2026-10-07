# Tech Migration AI — Phase 4: Personalized Learning

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
the tech catalog contents, and the `/api/convert` endpoint (all four blocks
+ explanation schema, style hint propagation, no-ellipsis rule in the prompt,
502 and 422 paths).

Frontend: `npm run build` (type-check + production build) must pass.

## Switch providers later

```bash
AI_PROVIDER=openai OPENAI_API_KEY=sk-... uvicorn main:app
```
The `AIProvider` interface is the seam: add new providers in
`backend/llm/provider.py` without touching business logic. `OpenAIProvider`
is currently a stub that raises until keys are configured.

## Phase 3: convert code

Open http://localhost:3000/convert (top nav: 🔄 Convert). Pick source and
target languages (+ versions) from the catalog (or free-text via "Other…"),
optionally add a style hint (`spring-controller`, `junit-test`, …), and paste
code — or hit 💡 to load the spec's Java → C# employee-filter example. You get:

1. **Original** — your code, unchanged.
2. **Direct translation** — the closest equivalent preserving structure.
3. **Idiomatic target** — how an experienced developer would write it
   (e.g. LINQ instead of a `foreach` loop).
4. **Modern target** — newer target features (records, pattern matching,
   collection expressions, …), only when genuinely better; otherwise it
   matches the idiomatic version and the explanation says why.
5. **Explanation** — what changed, why, what the target does differently,
   new capabilities, performance notes, common mistakes — plus an
   honestly-graded equivalence badge.

Each block has a one-tap copy button. If the model returns invalid JSON, the
UI shows the raw text and a retry hint.

API: `POST /api/convert` —
`{source_tech, source_version?, target_tech, target_version?, source_code,
style_hint?}` → `{source_code, direct_translation, idiomatic_target,
modern_target, equivalence, explanation:{what_changed[], why_changed[],
target_differences, new_capabilities[], performance_notes,
common_mistakes[], modern_note}}`.

Hard prompt rules: all four blocks must be complete, compilable-in-principle
code — never `...` placeholders; never invent APIs; preserve behavior;
respect the target version; flag constructs with no direct equivalent.

## Phase 4: personalized learning

Open http://localhost:3000/learn (top nav: 🎓 Learn).

1. **Setup** — "I already know" (add one or more tech entries, e.g. Java 17 +
   Spring Boot 3.2), "I want to learn" (e.g. C# .NET 8), your experience
   (Beginner / Intermediate / Advanced / Expert), and your goal (understand
   basics / become productive / migrate an application / become production-
   ready / interview preparation). Hit **Generate my path**.
2. **Path** — modules ordered simple → production, each topic showing what it
   maps to in your known stack ("← you know: Java Streams"), a "new in target"
   badge when there's no equivalent, and an estimated time. Every topic has a
   **☑ I already know this** toggle — it collapses from the path and is
   skipped when you regenerate. Known topics and your setup persist in the
   browser (localStorage); the backend stays stateless (server-side profiles
   are a later phase).
3. **Lesson** — pick a topic and an explanation level (1 Beginner, 2
   Developer, 3 Experienced, 4 Production). Level 3 explicitly contrasts the
   concept against what you already know; level 4 teaches production usage.
   Each lesson shows what stays the same / what changes / why, source and
   target examples, and the idiomatic form.
4. **Exercises** — per topic: basic, intermediate, production, and migration
   exercises. Submit a solution and the AI reviews it: verdict (correct /
   partial / incorrect), what you got right, what needs fixing, a better
   implementation, and target-language best practices.

API:
- `POST /api/learn/path` — `{known:[{name,version?}], target_tech,
  target_version?, experience, goal, skip_topics[]}` → `{path_title,
  modules:[{title, why_this_module, topics:[{title, known_equivalent,
  new_in_target, estimated_minutes}]}]}`.
- `POST /api/learn/topic` — `{known, target_tech, target_version?, topic,
  level:1|2|3|4}` → lesson JSON.
- `POST /api/learn/exercises` — `{known, target_tech, target_version?, topic,
  level}` → `{exercises:[{kind, title, prompt, starter_code?}]}`.
- `POST /api/learn/review` — `{exercise_title, exercise_prompt, target_tech,
  solution}` → `{verdict, correct_parts[], incorrect_parts[],
  better_implementation, best_practices[]}`.

Every path topic is anchored in the developer's known stack — never a generic
course. Topics the developer already knows are excluded server-side via
`skip_topics`.

Try the acceptance flow: known = Java + Spring Boot, target = C# (.NET 8),
goal = "become productive" → expect a path with a "Java → C# differences"
module; open the LINQ topic at level 3 → expect Streams contrast; submit an
exercise solution → expect a structured review.

## What's coming next

Phase 5 — RAG over official docs (ingestion, embeddings, vector DB, hybrid
retrieval, citations).
Then: repository analysis (Phase 6), automated migration with human approval
(Phase 7).

See the full plan: `~/workspace/your_files/tech-migration-ai-plan/tech-migration-ai-plan.pdf`.
