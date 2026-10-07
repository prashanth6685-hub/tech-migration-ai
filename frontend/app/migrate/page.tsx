"use client";

import { useEffect, useRef, useState } from "react";

import type { Catalog } from "../components/tech-picker";
import { TechPicker } from "../components/tech-picker";
import type { Citation } from "../components/grounding-badge";
import { GroundingBadge } from "../components/grounding-badge";
import { ReviewSection } from "./review";
import { API_URL } from "../lib/api";


type Equivalence = "exact" | "conceptual" | "partial" | "none";
type Severity = "red" | "yellow" | "green";

interface LanguageInfo {
  name: string;
  version: string;
  files: number;
}
interface Dependency {
  name: string;
  version: string;
  source: string;
}
interface Finding {
  severity: Severity;
  area: string;
  title: string;
  detail: string;
  deduction: number;
}
interface DetectedStack {
  languages: LanguageInfo[];
  frameworks: string[];
  build_systems: string[];
  databases: string[];
  orms: string[];
  testing_frameworks: string[];
  deployment: string[];
  ci: string[];
  config_files: string[];
  dependencies: Dependency[];
  auth_hints: string[];
  findings: Finding[];
  file_count: number;
  total_bytes: number;
}
interface ProjectSummary {
  project_id: string;
  file_count: number;
  total_bytes: number;
  detected: DetectedStack;
}
interface ReadinessIssue {
  severity: Severity;
  area: string;
  title: string;
  detail: string;
}
interface Readiness {
  scores: Record<string, number>;
  issues: ReadinessIssue[];
}
interface TechMappingRow {
  source: string;
  target: string;
  equivalence: Equivalence;
  notes: string;
}
interface RiskItem {
  area: string;
  severity: Severity;
  why: string;
  whatBreaks: string;
  solution: string;
  validation: string;
}
interface MigrationPhaseItem {
  name: string;
  description: string;
}
interface MigrationReport {
  summary: string;
  migrationDifficulty: string;
  overallRisk: string;
  technologyMapping: TechMappingRow[];
  breakingChanges: string[];
  dependencies: string[];
  codeChanges: string[];
  configurationChanges: string[];
  databaseChanges: string[];
  securityChanges: string[];
  testingChanges: string[];
  deploymentChanges: string[];
  observabilityChanges: string[];
  performanceChanges: string[];
  risks: RiskItem[];
  recommendations: string[];
  migrationPhases: MigrationPhaseItem[];
  validationStrategy: string[];
  rollbackStrategy: string[];
  examples: string[];
  sources: Citation[];
  grounded: boolean;
}
interface MigrationAnalysis {
  project_id: string;
  detected: DetectedStack;
  target_stack: Record<string, string>;
  readiness: Readiness;
  report: MigrationReport;
}

const AREAS: { id: string; label: string }[] = [
  { id: "code", label: "Code" },
  { id: "dependencies", label: "Dependencies" },
  { id: "database", label: "Database" },
  { id: "security", label: "Security" },
  { id: "testing", label: "Testing" },
  { id: "deployment", label: "Deployment" },
  { id: "configuration", label: "Configuration" },
];

const EQUIV_LABEL: Record<Equivalence, string> = {
  exact: "Exact",
  conceptual: "Conceptual",
  partial: "Partial",
  none: "None",
};
const EQUIV_BADGE: Record<Equivalence, string> = {
  exact: "badge--green",
  conceptual: "badge--blue",
  partial: "badge--amber",
  none: "badge--red",
};
const SEV_BADGE: Record<Severity, string> = {
  red: "badge--red",
  yellow: "badge--amber",
  green: "badge--green",
};
const SEV_LABEL: Record<Severity, string> = {
  red: "High risk",
  yellow: "Medium risk",
  green: "Low risk",
};

function scoreColor(score: number): string {
  if (score >= 75) return "var(--green)";
  if (score >= 50) return "var(--amber)";
  return "#dc2626";
}

function ScoreBar({ label, score }: { label: string; score: number }) {
  return (
    <div className="score-row">
      <span className="score-label">{label}</span>
      <div className="score-track">
        <div
          className="score-fill"
          style={{ width: `${score}%`, background: scoreColor(score) }}
        />
      </div>
      <span className="score-value">{score}%</span>
    </div>
  );
}

function ChangeSection({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <details className="acc">
      <summary>
        {title} <span className="muted">({items.length})</span>
      </summary>
      <ul className="expl-list">
        {items.map((s, i) => (
          <li key={i}>{s}</li>
        ))}
      </ul>
    </details>
  );
}

export default function MigratePage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  // Target stack
  const [tgtLang, setTgtLang] = useState("C#");
  const [tgtLangVer, setTgtLangVer] = useState(".NET 8");
  const [tgtFramework, setTgtFramework] = useState("ASP.NET Core");
  const [tgtRuntime, setTgtRuntime] = useState(".NET 8");
  const [tgtDb, setTgtDb] = useState("PostgreSQL");
  const [tgtOrm, setTgtOrm] = useState("EF Core");
  const [tgtTesting, setTgtTesting] = useState("xUnit");
  const [tgtBuild, setTgtBuild] = useState("NuGet");
  const [tgtDeploy, setTgtDeploy] = useState("Docker");
  // Project
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [uploading, setUploading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<MigrationAnalysis | null>(null);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch(`${API_URL}/api/tech/catalog`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: Catalog | null) => setCatalog(data))
      .catch(() => setCatalog(null));
  }, []);

  async function uploadZip(files: FileList | null) {
    const file = files?.[0];
    if (!file || uploading) return;
    setUploading(true);
    setError("");
    setProject(null);
    setAnalysis(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${API_URL}/api/migration/upload`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(
          typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`
        );
      }
      setProject((await res.json()) as ProjectSummary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function runAnalyze() {
    if (!project || analyzing) return;
    setAnalyzing(true);
    setError("");
    setAnalysis(null);
    try {
      const res = await fetch(`${API_URL}/api/migration/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.project_id,
          target_stack: {
            language: tgtLang,
            framework: tgtFramework,
            runtime: tgtRuntime,
            database: tgtDb,
            orm: tgtOrm,
            testing: tgtTesting,
            build: tgtBuild,
            deployment: tgtDeploy,
          },
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const detail = err.detail;
        throw new Error(
          typeof detail === "string"
            ? detail
            : detail?.error ?? `HTTP ${res.status}`
        );
      }
      setAnalysis((await res.json()) as MigrationAnalysis);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }

  const detected = project?.detected;
  const report = analysis?.report;
  const readiness = analysis?.readiness;
  const sevCounts = (sev: Severity) =>
    readiness?.issues.filter((i) => i.severity === sev).length ?? 0;

  return (
    <div className="page page--wide">
      <header className="header">
        <div className="header-title">Migrate Application</div>
      </header>

      {error && <p className="error">⚠️ {error}</p>}

      {/* ---- 1. Target stack ---- */}
      <section className="card">
        <h2>1. Target stack</h2>
        <p className="muted">
          Where should this application go? The source stack is detected
          automatically from your upload.
        </p>
        <div className="grid-2">
          <TechPicker
            label="Target language"
            catalog={catalog}
            value={tgtLang}
            onChange={setTgtLang}
            version={tgtLangVer}
            onVersionChange={setTgtLangVer}
          />
          <div className="field">
            <label className="label" htmlFor="tgt-framework">Framework</label>
            <input id="tgt-framework" className="input" value={tgtFramework}
              onChange={(e) => setTgtFramework(e.target.value)} placeholder="ASP.NET Core" />
          </div>
        </div>
        <div className="grid-2">
          <div className="field">
            <label className="label" htmlFor="tgt-runtime">Runtime / version</label>
            <input id="tgt-runtime" className="input" value={tgtRuntime}
              onChange={(e) => setTgtRuntime(e.target.value)} placeholder=".NET 8" />
          </div>
          <div className="field">
            <label className="label" htmlFor="tgt-db">Database</label>
            <input id="tgt-db" className="input" value={tgtDb}
              onChange={(e) => setTgtDb(e.target.value)} placeholder="PostgreSQL" />
          </div>
        </div>
        <div className="grid-2">
          <div className="field">
            <label className="label" htmlFor="tgt-orm">ORM</label>
            <input id="tgt-orm" className="input" value={tgtOrm}
              onChange={(e) => setTgtOrm(e.target.value)} placeholder="EF Core" />
          </div>
          <div className="field">
            <label className="label" htmlFor="tgt-testing">Testing framework</label>
            <input id="tgt-testing" className="input" value={tgtTesting}
              onChange={(e) => setTgtTesting(e.target.value)} placeholder="xUnit" />
          </div>
        </div>
        <div className="grid-2">
          <div className="field">
            <label className="label" htmlFor="tgt-build">Build system</label>
            <input id="tgt-build" className="input" value={tgtBuild}
              onChange={(e) => setTgtBuild(e.target.value)} placeholder="NuGet" />
          </div>
          <div className="field">
            <label className="label" htmlFor="tgt-deploy">Deployment</label>
            <input id="tgt-deploy" className="input" value={tgtDeploy}
              onChange={(e) => setTgtDeploy(e.target.value)} placeholder="Docker" />
          </div>
        </div>
      </section>

      {/* ---- 2. Upload ---- */}
      <section className="card">
        <h2>2. Upload application</h2>
        <p className="muted">
          Upload a ZIP of the project (max 50 MB). It is analyzed locally —
          never executed — and the source stack is detected automatically.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept=".zip"
          className="input"
          onChange={(e) => void uploadZip(e.target.files)}
          disabled={uploading}
        />
        {uploading && <p className="muted">Uploading and scanning…</p>}
        {detected && (
          <div className="result">
            <div className="result-head">
              <strong>Detected stack</strong>
              <span className="muted">
                {project!.file_count} files ·{" "}
                {(project!.total_bytes / 1024).toFixed(0)} KB
              </span>
            </div>
            <div className="chip-row">
              {detected.languages.map((l) => (
                <span key={l.name} className="chip chip--active">
                  {l.name}
                  {l.version ? ` ${l.version}` : ""} · {l.files} files
                </span>
              ))}
              {detected.frameworks.map((f) => (
                <span key={f} className="chip">{f}</span>
              ))}
              {detected.build_systems.map((b) => (
                <span key={b} className="chip">{b}</span>
              ))}
              {detected.orms.map((o) => (
                <span key={o} className="chip">{o}</span>
              ))}
              {detected.databases.map((d) => (
                <span key={d} className="chip">{d}</span>
              ))}
              {detected.testing_frameworks.map((t) => (
                <span key={t} className="chip">{t}</span>
              ))}
              {detected.deployment.map((d) => (
                <span key={d} className="chip">{d}</span>
              ))}
            </div>
            <button
              className="send-btn"
              type="button"
              onClick={() => void runAnalyze()}
              disabled={analyzing}
            >
              {analyzing ? "Analyzing… (this can take a minute)" : "Analyze migration"}
            </button>
          </div>
        )}
      </section>

      {/* ---- 3. Report dashboard ---- */}
      {readiness && report && (
        <>
          <section className="card">
            <div className="result-head">
              <h2>Migration readiness</h2>
              <GroundingBadge grounded={report.grounded} sources={report.sources} />
            </div>
            <div className="readiness-hero">
              <div
                className="readiness-overall"
                style={{ color: scoreColor(readiness.scores.overall) }}
              >
                {readiness.scores.overall}%
              </div>
              <div>
                <div className="chip-row">
                  <span className="badge badge--red">
                    ● {sevCounts("red")} high
                  </span>
                  <span className="badge badge--amber">
                    ● {sevCounts("yellow")} medium
                  </span>
                  <span className="badge badge--green">
                    ● {sevCounts("green")} low
                  </span>
                  <span className="badge badge--gray">
                    Difficulty: {report.migrationDifficulty}
                  </span>
                  <span className="badge badge--gray">
                    Risk: {report.overallRisk}
                  </span>
                </div>
              </div>
            </div>
            {AREAS.map((a) => (
              <ScoreBar
                key={a.id}
                label={a.label}
                score={readiness.scores[a.id] ?? 0}
              />
            ))}
          </section>

          <section className="card">
            <h2>Executive summary</h2>
            <p>{report.summary}</p>
            {report.recommendations.length > 0 && (
              <>
                <h3>Recommendations</h3>
                <ul className="expl-list">
                  {report.recommendations.map((r, i) => (
                    <li key={i}>{r}</li>
                  ))}
                </ul>
              </>
            )}
          </section>

          <section className="card">
            <h2>Detected issues</h2>
            <p className="muted">
              Computed deterministically from the code scan — not from the AI.
            </p>
            {(["red", "yellow", "green"] as Severity[]).map((sev) => {
              const items = readiness.issues.filter((i) => i.severity === sev);
              if (items.length === 0) return null;
              return (
                <div key={sev}>
                  <h3>
                    <span className={`badge ${SEV_BADGE[sev]}`}>
                      ● {SEV_LABEL[sev]} ({items.length})
                    </span>
                  </h3>
                  {items.map((issue, i) => (
                    <details key={i} className="acc">
                      <summary>
                        [{issue.area}] {issue.title}
                      </summary>
                      <p>{issue.detail}</p>
                    </details>
                  ))}
                </div>
              );
            })}
          </section>

          {report.technologyMapping.length > 0 && (
            <section className="card">
              <h2>Technology mapping</h2>
              <table className="map-table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Target</th>
                    <th>Equivalence</th>
                    <th>Notes</th>
                  </tr>
                </thead>
                <tbody>
                  {report.technologyMapping.map((row, i) => (
                    <tr key={i}>
                      <td>{row.source}</td>
                      <td>{row.target || "—"}</td>
                      <td>
                        <span className={`badge ${EQUIV_BADGE[row.equivalence]}`}>
                          {EQUIV_LABEL[row.equivalence]}
                        </span>
                      </td>
                      <td>{row.notes}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {report.risks.length > 0 && (
            <section className="card">
              <h2>Risk analysis</h2>
              {report.risks.map((risk, i) => (
                <details key={i} className="acc">
                  <summary>
                    <span className={`badge ${SEV_BADGE[risk.severity]}`}>
                      ● {SEV_LABEL[risk.severity]}
                    </span>{" "}
                    [{risk.area}] {risk.why.slice(0, 90)}
                    {risk.why.length > 90 ? "…" : ""}
                  </summary>
                  <dl className="kv">
                    <dt>Why it&apos;s risky</dt>
                    <dd>{risk.why}</dd>
                    <dt>What can break</dt>
                    <dd>{risk.whatBreaks}</dd>
                    <dt>Recommended solution</dt>
                    <dd>{risk.solution}</dd>
                    <dt>Validation</dt>
                    <dd>{risk.validation}</dd>
                  </dl>
                </details>
              ))}
            </section>
          )}

          <section className="card">
            <h2>Changes by area</h2>
            <ChangeSection title="Breaking changes" items={report.breakingChanges} />
            <ChangeSection title="Dependencies" items={report.dependencies} />
            <ChangeSection title="Code" items={report.codeChanges} />
            <ChangeSection title="Configuration" items={report.configurationChanges} />
            <ChangeSection title="Database" items={report.databaseChanges} />
            <ChangeSection title="Security" items={report.securityChanges} />
            <ChangeSection title="Testing" items={report.testingChanges} />
            <ChangeSection title="Deployment" items={report.deploymentChanges} />
            <ChangeSection title="Observability" items={report.observabilityChanges} />
            <ChangeSection title="Performance" items={report.performanceChanges} />
          </section>

          {report.migrationPhases.length > 0 && (
            <section className="card">
              <h2>Migration phases</h2>
              <ol className="phase-list">
                {report.migrationPhases.map((p, i) => (
                  <li key={i}>
                    <strong>{p.name}</strong>
                    <p className="muted">{p.description}</p>
                  </li>
                ))}
              </ol>
            </section>
          )}

          <section className="card">
            <div className="grid-2">
              <div>
                <h2>Validation strategy</h2>
                <ul className="expl-list">
                  {report.validationStrategy.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
              <div>
                <h2>Rollback strategy</h2>
                <ul className="expl-list">
                  {report.rollbackStrategy.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            </div>
            {report.examples.length > 0 && (
              <>
                <h2>Examples</h2>
                <ul className="expl-list">
                  {report.examples.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </>
            )}
          </section>

          {/* Phase 7: file-by-file review with human approval. */}
          {project && <ReviewSection projectId={project.project_id} />}
        </>
      )}
    </div>
  );
}
