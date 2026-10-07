"use client";

import { useEffect, useState } from "react";

import type { Catalog } from "../components/tech-picker";
import { TechPicker } from "../components/tech-picker";
import { renderMarkdown } from "../components/markdown";
import type { Citation } from "../components/grounding-badge";
import { GroundingBadge } from "../components/grounding-badge";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const PROFILE_KEY = "tmai-learn-profile";

type Experience = "beginner" | "intermediate" | "advanced" | "expert";
type Goal = "basics" | "productive" | "migrate" | "production" | "interview";
type Verdict = "correct" | "partial" | "incorrect";
type View = "form" | "path" | "lesson";

interface KnownTech {
  name: string;
  version: string;
}

interface PathTopic {
  title: string;
  known_equivalent: string;
  new_in_target: boolean;
  estimated_minutes: number;
}

interface PathModule {
  title: string;
  why_this_module: string;
  topics: PathTopic[];
}

interface LearningPath {
  path_title: string;
  modules: PathModule[];
}

interface Lesson {
  topic: string;
  level: number;
  level_name: string;
  what_stays_same: string;
  what_changes: string;
  why_different: string;
  source_example: string;
  target_example: string;
  idiomatic_target: string;
  new_capabilities: string[];
  production_notes: string;
  sources: Citation[];
  grounded: boolean;
}

interface Exercise {
  kind: "basic" | "intermediate" | "production" | "migration";
  title: string;
  prompt: string;
  starter_code: string;
}

interface ExerciseReview {
  verdict: Verdict;
  correct_parts: string[];
  incorrect_parts: string[];
  better_implementation: string;
  best_practices: string[];
}

const EXPERIENCES: { id: Experience; label: string }[] = [
  { id: "beginner", label: "Beginner" },
  { id: "intermediate", label: "Intermediate" },
  { id: "advanced", label: "Advanced" },
  { id: "expert", label: "Expert" },
];

const GOALS: { id: Goal; label: string }[] = [
  { id: "basics", label: "Understand basics" },
  { id: "productive", label: "Become productive" },
  { id: "migrate", label: "Migrate an application" },
  { id: "production", label: "Become production-ready" },
  { id: "interview", label: "Interview preparation" },
];

const LEVELS = [
  { n: 1, label: "1 · Beginner" },
  { n: 2, label: "2 · Developer" },
  { n: 3, label: "3 · Experienced" },
  { n: 4, label: "4 · Production" },
];

const KIND_BADGE: Record<Exercise["kind"], string> = {
  basic: "badge--green",
  intermediate: "badge--blue",
  production: "badge--amber",
  migration: "badge--gray",
};

const VERDICT_BADGE: Record<Verdict, string> = {
  correct: "badge--green",
  partial: "badge--amber",
  incorrect: "badge--red",
};

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <button
      type="button"
      className="copy-btn"
      onClick={() => void copy()}
      aria-label="Copy code to clipboard"
    >
      {copied ? "Copied ✓" : "⧉ Copy"}
    </button>
  );
}

function CodeBlock({ title, code }: { title: string; code: string }) {
  return (
    <div>
      <div className="code-head">
        <span className="label">{title}</span>
        <CopyButton text={code} />
      </div>
      <pre className="code-block">
        <code>{code.replace(/^\n+|\n+$/g, "")}</code>
      </pre>
    </div>
  );
}

export default function LearnPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [view, setView] = useState<View>("form");

  // Form state
  const [known, setKnown] = useState<KnownTech[]>([
    { name: "Java", version: "17" },
    { name: "Spring Boot", version: "3.2" },
  ]);
  const [targetTech, setTargetTech] = useState("C#");
  const [targetVer, setTargetVer] = useState(".NET 8");
  const [experience, setExperience] = useState<Experience>("advanced");
  const [goal, setGoal] = useState<Goal>("productive");
  const [knownTopics, setKnownTopics] = useState<string[]>([]);

  // Path / lesson state
  const [path, setPath] = useState<LearningPath | null>(null);
  const [topic, setTopic] = useState("");
  const [level, setLevel] = useState(3);
  const [lesson, setLesson] = useState<Lesson | null>(null);
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [showExercises, setShowExercises] = useState(false);
  const [solutions, setSolutions] = useState<Record<number, string>>({});
  const [reviews, setReviews] = useState<Record<number, ExerciseReview>>({});
  const [reviewing, setReviewing] = useState<Record<number, boolean>>({});

  const [loading, setLoading] = useState(false);
  const [loadingLesson, setLoadingLesson] = useState(false);
  const [loadingExercises, setLoadingExercises] = useState(false);
  const [error, setError] = useState("");

  // Load catalog + persisted profile.
  useEffect(() => {
    fetch(`${API_URL}/api/tech/catalog`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: Catalog) => setCatalog(data))
      .catch(() => setCatalog(null));
    try {
      const raw = localStorage.getItem(PROFILE_KEY);
      if (raw) {
        const p = JSON.parse(raw) as {
          knownTopics?: string[];
          known?: KnownTech[];
          targetTech?: string;
          targetVer?: string;
          experience?: Experience;
          goal?: Goal;
        };
        if (p.knownTopics) setKnownTopics(p.knownTopics);
        if (p.known && p.known.length > 0) setKnown(p.known);
        if (p.targetTech) setTargetTech(p.targetTech);
        if (p.targetVer) setTargetVer(p.targetVer);
        if (p.experience) setExperience(p.experience);
        if (p.goal) setGoal(p.goal);
      }
    } catch {
      /* ignore corrupt profile */
    }
  }, []);

  // Persist the knowledge profile.
  useEffect(() => {
    try {
      localStorage.setItem(
        PROFILE_KEY,
        JSON.stringify({ knownTopics, known, targetTech, targetVer, experience, goal })
      );
    } catch {
      /* storage unavailable */
    }
  }, [knownTopics, known, targetTech, targetVer, experience, goal]);

  function toggleKnownTopic(title: string) {
    setKnownTopics((prev) =>
      prev.includes(title) ? prev.filter((t) => t !== title) : [...prev, title]
    );
  }

  function updateKnown(i: number, patch: Partial<KnownTech>) {
    setKnown((prev) => prev.map((t, j) => (j === i ? { ...t, ...patch } : t)));
  }

  function post<T>(url: string, body: unknown): Promise<T> {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(async (res) => {
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const err = await res.json();
          detail = err.detail?.error ?? detail;
        } catch {
          /* keep default */
        }
        throw new Error(detail);
      }
      return (await res.json()) as T;
    });
  }

  const cleanKnown = () => known.filter((t) => t.name.trim());

  async function generatePath() {
    const clean = cleanKnown();
    if (clean.length === 0 || !targetTech || loading) return;
    setLoading(true);
    setError("");
    setPath(null);
    setView("path");
    try {
      const result = await post<LearningPath>(`${API_URL}/api/learn/path`, {
        known: clean.map((t) => ({
          name: t.name,
          version: t.version || undefined,
        })),
        target_tech: targetTech,
        target_version: targetVer || undefined,
        experience,
        goal,
        skip_topics: knownTopics,
      });
      setPath(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  async function loadLesson(topicTitle: string, lvl: number) {
    const clean = cleanKnown();
    if (clean.length === 0 || !targetTech || loadingLesson) return;
    setLoadingLesson(true);
    setError("");
    setLesson(null);
    setShowExercises(false);
    setExercises([]);
    setSolutions({});
    setReviews({});
    try {
      const result = await post<Lesson>(`${API_URL}/api/learn/topic`, {
        known: clean.map((t) => ({
          name: t.name,
          version: t.version || undefined,
        })),
        target_tech: targetTech,
        target_version: targetVer || undefined,
        topic: topicTitle,
        level: lvl,
      });
      setLesson(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoadingLesson(false);
    }
  }

  function openLesson(topicTitle: string, lvl: number) {
    setTopic(topicTitle);
    setLevel(lvl);
    setView("lesson");
    void loadLesson(topicTitle, lvl);
  }

  async function loadExercises() {
    const clean = cleanKnown();
    if (clean.length === 0 || !topic || loadingExercises) return;
    setLoadingExercises(true);
    setError("");
    try {
      const result = await post<{ exercises: Exercise[] }>(
        `${API_URL}/api/learn/exercises`,
        {
          known: clean.map((t) => ({
            name: t.name,
            version: t.version || undefined,
          })),
          target_tech: targetTech,
          target_version: targetVer || undefined,
          topic,
          level,
        }
      );
      setExercises(result.exercises);
      setShowExercises(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoadingExercises(false);
    }
  }

  async function submitExercise(i: number, ex: Exercise) {
    const solution = solutions[i];
    if (!solution?.trim() || reviewing[i]) return;
    setReviewing((prev) => ({ ...prev, [i]: true }));
    setError("");
    try {
      const result = await post<ExerciseReview>(
        `${API_URL}/api/learn/review`,
        {
          exercise_title: ex.title,
          exercise_prompt: ex.prompt,
          target_tech: targetTech,
          target_version: targetVer || undefined,
          solution,
        }
      );
      setReviews((prev) => ({ ...prev, [i]: result }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setReviewing((prev) => ({ ...prev, [i]: false }));
    }
  }

  const knownList = known.map((t) => t.name).filter(Boolean).join(", ");

  return (
    <div className="page page--wide">
      <header className="header">
        <div className="header-title">Learn a New Technology</div>
        {!catalog && (
          <span className="badge badge--amber">
            ● catalog offline — type tech names manually
          </span>
        )}
      </header>

      {view === "form" && (
        <section className="card">
          <h2>Your learning setup</h2>
          <p className="muted">
            Tell me what you already know and what you want to learn — the path
            is built around your knowledge, never a generic course.
          </p>

          <div className="label">I already know</div>
          {known.map((t, i) => (
            <div className="field" key={i}>
              <div className="field-row">
                <div style={{ flex: 1 }}>
                  <TechPicker
                    label={`Known technology ${i + 1}`}
                    catalog={catalog}
                    value={t.name}
                    onChange={(v) => updateKnown(i, { name: v })}
                    version={t.version}
                    onVersionChange={(v) => updateKnown(i, { version: v })}
                  />
                </div>
                {known.length > 1 && (
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => setKnown((prev) => prev.filter((_, j) => j !== i))}
                    aria-label="Remove technology"
                  >
                    ✕
                  </button>
                )}
              </div>
            </div>
          ))}
          <div className="suggestion-row">
            <button
              type="button"
              className="chip"
              onClick={() => setKnown((prev) => [...prev, { name: "", version: "" }])}
            >
              ➕ Add another technology
            </button>
          </div>

          <div className="grid-2">
            <div className="field">
              <div className="label">I want to learn</div>
              <TechPicker
                label="Target technology"
                catalog={catalog}
                value={targetTech}
                onChange={setTargetTech}
                version={targetVer}
                onVersionChange={setTargetVer}
              />
            </div>
          </div>

          <div className="field">
            <div className="label">My experience</div>
            <div className="suggestion-row">
              {EXPERIENCES.map((e) => (
                <button
                  key={e.id}
                  type="button"
                  className={`chip${experience === e.id ? " chip--active" : ""}`}
                  onClick={() => setExperience(e.id)}
                  aria-pressed={experience === e.id}
                >
                  {e.label}
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <div className="label">Learning goal</div>
            <select
              className="select"
              value={goal}
              onChange={(e) => setGoal(e.target.value as Goal)}
              aria-label="Learning goal"
            >
              {GOALS.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.label}
                </option>
              ))}
            </select>
          </div>

          {knownTopics.length > 0 && (
            <p className="muted">
              ☑ {knownTopics.length} topic{knownTopics.length === 1 ? "" : "s"} already
              marked as known — they&apos;ll be skipped.
            </p>
          )}

          <button
            className="send-btn"
            type="button"
            onClick={() => void generatePath()}
            disabled={loading || cleanKnown().length === 0 || !targetTech}
          >
            {loading ? "Building your path…" : "Generate my path"}
          </button>
          {error && <p className="error">⚠️ {error}</p>}
        </section>
      )}

      {view === "path" && (
        <section className="card">
          <div className="suggestion-row">
            <button type="button" className="link-btn" onClick={() => setView("form")}>
              ← Edit setup
            </button>
            <button
              type="button"
              className="link-btn"
              onClick={() => void generatePath()}
              disabled={loading}
            >
              ↻ Regenerate (skips known topics)
            </button>
          </div>
          {loading && <p className="muted">Building your path…</p>}
          {error && <p className="error">⚠️ {error}</p>}
          {path && (
            <div className="result">
              <div className="result-head">
                <strong>{path.path_title}</strong>
                <span className="muted">
                  {knownList} → {targetTech}
                  {targetVer ? ` ${targetVer}` : ""}
                </span>
              </div>
              {path.modules.map((m, mi) => {
                const remaining = m.topics.filter((t) => !knownTopics.includes(t.title));
                return (
                  <div key={mi}>
                    <h3>
                      {mi + 1}. {m.title}
                    </h3>
                    <p className="muted">{m.why_this_module}</p>
                    {remaining.length === 0 && (
                      <p className="muted">☑ All topics in this module already known.</p>
                    )}
                    {remaining.map((t) => (
                      <div className="field-row" key={t.title}>
                        <div style={{ flex: 1 }}>
                          <strong>{t.title}</strong>{" "}
                          {t.new_in_target && (
                            <span className="badge badge--blue">new in target</span>
                          )}{" "}
                          {t.known_equivalent && (
                            <span className="muted">← you know: {t.known_equivalent}</span>
                          )}{" "}
                          <span className="muted">· ~{t.estimated_minutes} min</span>
                        </div>
                        <label className="muted" style={{ whiteSpace: "nowrap" }}>
                          <input
                            type="checkbox"
                            checked={knownTopics.includes(t.title)}
                            onChange={() => toggleKnownTopic(t.title)}
                          />{" "}
                          I already know this
                        </label>
                        <button
                          type="button"
                          className="chip"
                          onClick={() => openLesson(t.title, level)}
                        >
                          Learn →
                        </button>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {view === "lesson" && (
        <section className="card">
          <div className="suggestion-row">
            <button type="button" className="link-btn" onClick={() => setView("path")}>
              ← Back to path
            </button>
          </div>
          {loadingLesson && <p className="muted">Preparing your lesson…</p>}
          {error && <p className="error">⚠️ {error}</p>}
          {lesson && (
            <div className="result">
              <div className="result-head">
                <strong>{lesson.topic}</strong>
                <span className="muted">
                  for a {knownList || "developer"} developer
                </span>
                <GroundingBadge
                  grounded={lesson.grounded}
                  sources={lesson.sources}
                />
              </div>
              <div className="suggestion-row">
                {LEVELS.map((l) => (
                  <button
                    key={l.n}
                    type="button"
                    className={`chip${level === l.n ? " chip--active" : ""}`}
                    onClick={() => {
                      setLevel(l.n);
                      void loadLesson(topic, l.n);
                    }}
                    aria-pressed={level === l.n}
                    disabled={loadingLesson}
                  >
                    {l.label}
                  </button>
                ))}
              </div>
              <dl className="kv">
                {lesson.what_stays_same && (
                  <>
                    <dt>What stays the same</dt>
                    <dd>{lesson.what_stays_same}</dd>
                  </>
                )}
                <dt>What changes</dt>
                <dd>{lesson.what_changes}</dd>
                <dt>Why it&apos;s different</dt>
                <dd>{lesson.why_different}</dd>
              </dl>
              <CodeBlock title={`${knownList || "Source"} example`} code={lesson.source_example} />
              <CodeBlock title={`${targetTech} example`} code={lesson.target_example} />
              <CodeBlock
                title={`${targetTech} — idiomatic`}
                code={lesson.idiomatic_target}
              />
              {lesson.new_capabilities.length > 0 && (
                <>
                  <h3>New capabilities</h3>
                  <ul className="expl-list">
                    {lesson.new_capabilities.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                </>
              )}
              {lesson.production_notes && (
                <>
                  <h3>Production notes</h3>
                  <div className="muted">{renderMarkdown(lesson.production_notes)}</div>
                </>
              )}
              {!showExercises && (
                <button
                  className="send-btn"
                  type="button"
                  onClick={() => void loadExercises()}
                  disabled={loadingExercises}
                >
                  {loadingExercises ? "Creating exercises…" : "Practice with exercises"}
                </button>
              )}
              {showExercises &&
                exercises.map((ex, i) => (
                  <div key={i} className="result">
                    <div className="result-head">
                      <strong>
                        {ex.title}
                      </strong>
                      <span className={`badge ${KIND_BADGE[ex.kind]}`}>{ex.kind}</span>
                    </div>
                    <div className="muted">{renderMarkdown(ex.prompt)}</div>
                    <div className="field">
                      <label className="label" htmlFor={`sol-${i}`}>
                        Your solution
                      </label>
                      <textarea
                        id={`sol-${i}`}
                        className="input code-input"
                        value={solutions[i] ?? ex.starter_code}
                        onChange={(e) =>
                          setSolutions((prev) => ({ ...prev, [i]: e.target.value }))
                        }
                        placeholder="Write your solution here…"
                        spellCheck={false}
                      />
                    </div>
                    {!reviews[i] && (
                      <button
                        className="send-btn"
                        type="button"
                        onClick={() => void submitExercise(i, ex)}
                        disabled={
                          reviewing[i] || !(solutions[i] ?? ex.starter_code).trim()
                        }
                      >
                        {reviewing[i] ? "Reviewing…" : "Submit for review"}
                      </button>
                    )}
                    {reviews[i] && (
                      <div>
                        <p>
                          <span
                            className={`badge ${VERDICT_BADGE[reviews[i].verdict]}`}
                          >
                            ● {reviews[i].verdict}
                          </span>
                        </p>
                        {reviews[i].correct_parts.length > 0 && (
                          <>
                            <h4>What you got right</h4>
                            <ul className="expl-list">
                              {reviews[i].correct_parts.map((s, j) => (
                                <li key={j}>{s}</li>
                              ))}
                            </ul>
                          </>
                        )}
                        {reviews[i].incorrect_parts.length > 0 && (
                          <>
                            <h4>What needs fixing</h4>
                            <ul className="expl-list">
                              {reviews[i].incorrect_parts.map((s, j) => (
                                <li key={j}>{s}</li>
                              ))}
                            </ul>
                          </>
                        )}
                        <CodeBlock
                          title="Better implementation"
                          code={reviews[i].better_implementation}
                        />
                        {reviews[i].best_practices.length > 0 && (
                          <>
                            <h4>Best practices</h4>
                            <ul className="expl-list">
                              {reviews[i].best_practices.map((s, j) => (
                                <li key={j}>{s}</li>
                              ))}
                            </ul>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
