"""Prompt layers. Layer 1 (system) is fixed; task templates get added in later phases."""

# ---------------------------------------------------------------------------
# Phase 6 — Migration report task template (prompt layer 2)
# ---------------------------------------------------------------------------

MIGRATION_REPORT_TEMPLATE = """Analyze this REAL application for migration. The source facts below were
produced by static analysis — treat them as ground truth, not as suggestions.
Do NOT invent files, dependencies, or architecture the facts do not show.

SOURCE APPLICATION (static-analysis facts):
{facts}

TARGET STACK:
{target_stack}

DETERMINISTIC READINESS SCORES (computed from the facts — do NOT invent
different numbers; your job is to EXPLAIN what drives each score and what
would raise it):
{scores}

{EQUIVALENCE_GRADES}

Return the migration report as JSON with EXACTLY these fields:
- summary: 3-5 sentences — what the application is, why migration is needed,
  overall complexity and risk.
- migrationDifficulty: one of Low | Medium | High.
- overallRisk: one of Low | Medium | High.
- technologyMapping: rows {{source, target, equivalence, notes}} — one per
  stack area (language, framework, runtime, database, ORM, testing, build,
  deployment, logging, configuration). Grade every row honestly.
- breakingChanges: concrete breaking changes between the detected source
  versions and the target (APIs removed/renamed, behavior changes).
- dependencies: per-dependency findings — deprecated, unsupported, or
  replaced libraries with their target equivalents.
- codeChanges: language-level changes (types, generics, async, exceptions…).
- configurationChanges: config file/format changes.
- databaseChanges: ORM, query, migration-tooling changes.
- securityChanges: auth/authn, secrets, headers, CORS changes.
- testingChanges: test framework conversion and new tests needed.
- deploymentChanges: container/CI/CD/platform changes.
- observabilityChanges: logging, metrics, tracing, health checks.
- performanceChanges: threading, pooling, caching implications.
- risks: list of {{area, severity (red|yellow|green), why, whatBreaks,
  solution, validation}}. Every red risk MUST explain all four: why it is
  risky, what can break, the recommended solution, and how to validate.
- recommendations: prioritized, concrete next steps.
- migrationPhases: the incremental plan as ordered phases {{name,
  description}}. Follow these 10 stages: 1 Understand application,
  2 Analyze dependencies, 3 Identify incompatibilities, 4 Create migration
  plan, 5 Convert individual components, 6 Generate target code,
  7 Generate tests, 8 Static analysis, 9 Migration review, 10 Human approval.
- validationStrategy: how to prove each phase worked.
- rollbackStrategy: how to back out safely at each stage.
- examples: short illustrative code/config snippets (source -> target).

HARD RULES:
- NEVER invent APIs, libraries, configuration properties, or framework behavior.
- Prefer incremental migration; do not recommend a big-bang rewrite without a
  technical reason grounded in the facts.
- Consider security, performance, testing, deployment, and observability.
- When the facts are thin (e.g. no framework detected), say what is unknown
  instead of guessing.
"""

SYSTEM_PROMPT = """You are a Senior Software Architect, Technology Migration Expert, Code Conversion Expert, and Developer Learning Assistant.

Your responsibilities:
1. Analyze applications migrating from one technology to another.
2. Identify architectural, code, dependency, database, security, testing, configuration, deployment, and operational changes.
3. Explain migration risks and breaking changes.
4. Provide phased migration strategies.
5. Convert code between technologies when requested.
6. Explain the difference between direct code translation and idiomatic implementation.
7. Teach new technologies using the user's existing technology knowledge.
8. Map equivalent concepts between technologies.
9. Explain what remains the same, what changes, and what is completely new.
10. Recommend modern capabilities available in the target technology.

IMPORTANT RULES:
- Never assume two technologies are identical. Clearly distinguish exact equivalents from conceptual equivalents.
- Do not blindly translate syntax. Prefer idiomatic and modern target-language code.
- Explain why the target implementation differs.
- Identify deprecated and obsolete approaches.
- Prefer official documentation and current best practices.
- Clearly identify uncertainty.
- NEVER invent APIs, libraries, configuration properties, or framework behavior. If you are unsure whether an API exists, say so explicitly.
- Consider technology versions.
- Do not recommend rewriting an entire application without a technical reason.
- Prefer incremental migration when practical.
- Consider security, performance, testing, deployment, and observability.
- When comparing technologies, always anchor the explanation in what the user already knows: show the source implementation, the target implementation, the key difference, target-specific improvements, common migration problems, and the recommended approach.
- When teaching, skip concepts the user has already mastered unless there is an important difference worth calling out.
"""

# ---------------------------------------------------------------------------
# Phase 3 — Code conversion task template (prompt layer 2)
# ---------------------------------------------------------------------------

CODE_CONVERT_TEMPLATE = """Convert this source code to the target technology, returning FOUR
versions plus an explanation. This is not a line-by-line translation exercise:
the goal is working, natural target code an experienced developer would write.

Source technology: {source_tech}{source_version}
Target technology: {target_tech}{target_version}
{style_hint_line}
Source code:
```
{source_code}
```

{EQUIVALENCE_GRADES}

Return:
1. source_code: the original code, unchanged.
2. direct_translation: the closest equivalent target-language implementation that
   preserves the source structure and behavior. Only this block may mirror the
   source line-for-line; where a construct has no direct equivalent, say so in
   the explanation and make the closest behavior-preserving choice.
3. idiomatic_target: how an experienced {target_tech} developer would normally
   write this — natural APIs, idioms, and conventions of the target technology.
4. modern_target: the implementation using the target technology's newer or
   better features (e.g. C# records, pattern matching, collection expressions;
   Java records, sealed classes, virtual threads; Python type hints, match
   statements) — ONLY when genuinely better for this code. If the target offers
   nothing meaningfully newer here, return the same code as idiomatic_target and
   say so in the explanation's target-specific-improvement field... (as
   modern_note instead). Do not pad with cosmetic differences.
5. explanation:
   - what_changed: concrete list of what differs between original and idiomatic.
   - why_changed: the reason behind each significant change.
   - target_differences: what the target technology does differently at a
     language/platform level (type system, memory, async model, etc.).
   - new_capabilities: target-only capabilities the conversion can now use.
   - performance_notes: performance implications (deferred vs eager execution,
     allocations, async overhead, etc.).
   - common_mistakes: migration mistakes developers most often make with this
     pattern.
   - modern_note: when modern_target equals idiomatic_target, one sentence
     saying why there is nothing newer to gain here; otherwise "".
6. equivalence: one of exact | conceptual | partial | none, grading how
   faithfully the idiomatic version captures the source (per the grades above).
   Where the idiomatic version is a redesign rather than a translation, grade it
   "partial" or "none" and say what changed in target_differences.

HARD RULES:
- All four code blocks must be complete, compilable-in-principle code. NEVER
  use `...` or `// rest of code` placeholders inside a code block.
- NEVER invent APIs, libraries, configuration properties, or framework behavior.
- Preserve behavior: the idiomatic and modern versions must do the same thing
  as the source. If behavior cannot be preserved exactly, say so in
  target_differences.
- Respect the versions given: do not use features newer than the target version.
"""

# ---------------------------------------------------------------------------
# Phase 4 — Personalized learning task templates (prompt layer 2)
# ---------------------------------------------------------------------------

LEARN_PATH_TEMPLATE = """Generate a PERSONALIZED learning path for a developer who already
knows these technologies and wants to learn the target. This must NOT be a
generic course — every topic is anchored in what they already know.

Developer already knows:
{known_block}

Wants to learn:
Target technology: {target_tech}{target_version}
Experience level: {experience}
Learning goal: {goal_description}

{skip_block}
{EQUIVALENCE_GRADES}

Return a path of ordered modules, from simple to production. For each topic:
- title: the topic name in the target technology.
- known_equivalent: what this maps to in the technology they already know
  (e.g. "Java Streams" for a LINQ topic), or "" when there is no equivalent
  they know — set new_in_target to true in that case.
- new_in_target: true when the target has something genuinely new here that
  does not map to their known stack.
- estimated_minutes: realistic study time for this topic at their experience
  level (a number, no ranges).

Guiding example (Java + Spring Boot + Hibernate + Maven -> C# + .NET 8 +
ASP.NET Core + EF Core): modules "C# fundamentals", "Java -> C# differences"
(Streams->LINQ, CompletableFuture->Task, Maven->NuGet, annotations->attributes,
records->records, getters/setters->properties), "ASP.NET Core", "EF Core",
"Production" (Docker, logging, health checks, OpenTelemetry, CI/CD).

Tailor depth to the goal: "understand basics" stays shallow and skips
production modules; "become productive" covers everyday work deeply;
"migrate an application" leads with differences and migration hazards;
"become production-ready" goes deep on ops concerns; "interview preparation"
emphasizes concepts interviewers ask about plus practice questions.

HARD RULES:
- Every topic must connect to their known stack via known_equivalent, or be
  honestly marked new_in_target. Never a topic list that could have been
  written without knowing what they already know.
- Do not include topics that are 100% identical to what they already know
  unless the target version of it has an important difference worth teaching.
- Skip the listed already-known topics entirely — do not include them.
- NEVER invent APIs, libraries, configuration properties, or framework behavior.
- Respect the target version: do not teach features newer than it.
"""

LEARN_TOPIC_TEMPLATE = """Teach ONE topic to a developer who already knows {known_list}.

Target technology: {target_tech}{target_version}
Topic: {topic}
Explanation level: {level} — {level_name}

Level guide:
- 1 Beginner: plain-language idea. Tiny examples, minimal jargon, assume they
  know only the basics of their current stack.
- 2 Developer: technical mechanics — how it works, types, syntax, common
  patterns. Code-first.
- 3 Experienced: contrast explicitly against what they already know from
  {known_list}: what is the same, what is different, WHY it is different,
  and what the target provides that their stack does not (or vice versa).
- 4 Production: how this is actually used in a real system — configuration,
  pitfalls, performance, observability, testing, security. Real patterns,
  not textbook ones.

Provide:
1. topic and level_name (one of: Beginner, Developer, Experienced, Production).
2. what_stays_same: what carries over from their known technology (empty string
   if nothing does).
3. what_changes: what is different in the target technology.
4. why_different: why the target does it this way (design philosophy, history,
   platform constraints — real reasons, not speculation).
5. source_example: a short, correct code example in their known technology
   (pick the most relevant of: {known_list}).
6. target_example: the same idea in the target technology.
7. idiomatic_target: how an experienced {target_tech} developer would normally
   write it — may differ from target_example when the direct mapping is
   unidiomatic.
8. new_capabilities: target-only capabilities this topic unlocks.
9. production_notes: at level 4 this is the heart of the lesson — how to run
   this in production safely and observably. At lower levels, a brief note on
   what production usage demands, or an empty string if nothing is notable.

HARD RULES:
- NEVER invent APIs, libraries, configuration properties, or framework behavior.
- All code blocks must be complete and compilable-in-principle. No `...`
  placeholders inside code.
- Respect the target version.
"""

LEARN_EXERCISES_TEMPLATE = """Create practice exercises for a developer who knows {known_list}
and is learning {target_tech}{target_version}.

Topic: {topic}
Level: {level} — {level_name}

Return exactly 4 exercises, one of each kind:
- basic: reinforce the core idea with a small, guided task.
- intermediate: combine the topic with a nearby concept; some independent
  thinking required.
- production: a realistic task as it would appear in a production codebase
  (error handling, config, edge cases matter).
- migration: convert a short snippet from their known technology
  ({known_list}) to the target technology — include the snippet in the prompt
  so the exercise is self-contained.

For each exercise: kind, title, prompt (clear instructions, includes any needed
snippet), starter_code (optional scaffolding, empty string when not needed).

HARD RULES: exercises must be solvable with real {target_tech} APIs —
NEVER invent APIs or libraries.
"""

LEARN_REVIEW_TEMPLATE = """Review a developer's submitted solution.

Target technology: {target_tech}{target_version}
Exercise: {exercise_title}
Exercise prompt:
```
{exercise_prompt}
```

Their solution:
```
{solution}
```

Provide:
1. verdict: "correct" (works and is idiomatic), "partial" (works but has
   issues, or close but broken), or "incorrect" (wrong approach or broken).
2. correct_parts: what they got right — be specific, reference their code.
3. incorrect_parts: what is wrong or missing — be specific. Empty list when
   the solution is fully correct.
4. better_implementation: a complete, correct, idiomatic {target_tech} version
   of the solution — complete code, no `...` placeholders.
5. best_practices: target-language best practices relevant to this exercise.

Be encouraging but honest. NEVER invent APIs, libraries, or framework behavior.
"""

GOAL_DESCRIPTIONS = {
    "basics": "Understand the basics of the target technology",
    "productive": "Become productive with the target technology for daily work",
    "migrate": "Migrate an application from the known stack to the target",
    "production": "Become production-ready with the target technology",
    "interview": "Prepare for interviews on the target technology",
}

LEVEL_NAMES = {1: "Beginner", 2: "Developer", 3: "Experienced", 4: "Production"}

EQUIVALENCE_GRADES = """
EQUIVALENCE GRADES — you MUST label every mapping honestly:
- "exact": identical semantics and usage; a true drop-in replacement. This is RARE.
  Only use it when you are certain the behavior matches fully.
- "conceptual": the same underlying idea, but different mechanics, APIs, or idioms.
  Always name the key difference.
- "partial": covers only part of the source concept. Name what is missing or
  behaves differently.
- "none": no direct equivalent exists. Say what the developer should do instead.

RULES: default to "conceptual" or "partial" unless the match is truly identical.
NEVER label something "exact" when you are uncertain. Never invent APIs,
libraries, configuration properties, or framework behavior.
"""

CONCEPT_COMPARE_TEMPLATE = """Compare one concept between two technologies for a developer
who already knows the source technology.

Source technology: {source_tech}{source_version}
Target technology: {target_tech}{target_version}
Concept: {concept}

{EQUIVALENCE_GRADES}

Provide:
1. source_technology and target_technology (include versions when given).
2. concept: the concept name as asked.
3. equivalence: one of exact | conceptual | partial | none, per the grades above.
4. source_implementation: a short, correct code example in the source technology.
5. target_implementation: the target-technology code. Prefer the idiomatic form an
   experienced developer would write, not a line-by-line translation.
6. key_difference: what is fundamentally different between the two.
7. target_specific_improvement: a capability the target technology offers here that
   the source does not (or an empty string if none).
8. common_migration_problem: the mistake developers most often make moving this
   concept across (or an empty string if none).
9. recommended_approach: how to handle this concept in a real migration.
"""

STACK_MAPPING_TEMPLATE = """Map a source technology stack to a target technology stack, row by row.

Source stack:
{source_stack}

Target stack:
{target_stack}

{EQUIVALENCE_GRADES}

Return one row per stack area that is present in either stack: language,
framework, runtime, database, orm, testing, build, deployment, logging,
configuration. For each row give:
- source: the source technology for that area (or "" if the source has none).
- target: the target technology for that area (or "" if there is no equivalent).
- equivalence: one of exact | conceptual | partial | none, per the grades above.
- note: one sentence explaining the mapping, the difference, or what to do
  when there is no equivalent.
"""

CODE_COMPARE_TEMPLATE = """Compare this source code with its closest equivalent in the target technology.

Source technology: {source_tech}
Target technology: {target_tech}

Source code:
```
{source_code}
```

Return:
1. source_code: the original code, unchanged.
2. target_code: the closest equivalent target-language implementation — write it
   the way an experienced developer in the target technology would.
3. notes: a short list of the important differences a developer moving this code
   must know (syntax, semantics, pitfalls, performance). Each note is one or two
   sentences. Never invent APIs.
"""
