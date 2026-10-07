"use client";

import { useEffect, useState } from "react";

import { renderMarkdown } from "../components/markdown";
import type { Catalog } from "../components/tech-picker";
import { TechPicker } from "../components/tech-picker";
import type { Citation } from "../components/grounding-badge";
import { GroundingBadge } from "../components/grounding-badge";
import { API_URL } from "../lib/api";


type Equivalence = "exact" | "conceptual" | "partial" | "none";

interface ConceptComparison {
  source_technology: string;
  target_technology: string;
  concept: string;
  equivalence: Equivalence;
  source_implementation: string;
  target_implementation: string;
  key_difference: string;
  target_specific_improvement: string;
  common_migration_problem: string;
  recommended_approach: string;
  sources: Citation[];
  grounded: boolean;
}

interface MappingRow {
  source: string;
  target: string;
  equivalence: Equivalence;
  note: string;
}

interface CodeComparison {
  source_code: string;
  target_code: string;
  notes: string[];
}

const EQUIV_LABEL: Record<Equivalence, string> = {
  exact: "Exact equivalent",
  conceptual: "Conceptually similar",
  partial: "Partial equivalent",
  none: "No direct equivalent",
};

const EQUIV_BADGE: Record<Equivalence, string> = {
  exact: "badge--green",
  conceptual: "badge--blue",
  partial: "badge--amber",
  none: "badge--red",
};

const STACK_FIELDS = [
  "language",
  "framework",
  "runtime",
  "database",
  "orm",
  "testing",
  "build",
  "deployment",
] as const;

function EquivalenceBadge({ value }: { value: Equivalence }) {
  return (
    <span className={`badge ${EQUIV_BADGE[value]}`}>● {EQUIV_LABEL[value]}</span>
  );
}

function CodeBlock({ code }: { code: string }) {
  return (
    <pre className="code-block">
      <code>{code.replace(/^\n+|\n+$/g, "")}</code>
    </pre>
  );
}

/* ---------- Compare page ---------- */

export default function ComparePage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);

  // Concept section
  const [srcTech, setSrcTech] = useState("Java");
  const [srcVer, setSrcVer] = useState("17");
  const [tgtTech, setTgtTech] = useState("C#");
  const [tgtVer, setTgtVer] = useState(".NET 8");
  const [concept, setConcept] = useState("");
  const [conceptResult, setConceptResult] = useState<ConceptComparison | null>(null);
  const [conceptLoading, setConceptLoading] = useState(false);
  const [conceptError, setConceptError] = useState("");

  // Mapping section
  const [srcStack, setSrcStack] = useState<Record<string, string>>({
    language: "Java",
    framework: "Spring Boot",
    build: "Maven",
    database: "PostgreSQL",
  });
  const [tgtStack, setTgtStack] = useState<Record<string, string>>({
    language: "C#",
    framework: "ASP.NET Core",
    build: "NuGet",
    database: "PostgreSQL",
  });
  const [mapRows, setMapRows] = useState<MappingRow[] | null>(null);
  const [mapLoading, setMapLoading] = useState(false);
  const [mapError, setMapError] = useState("");

  // Code section
  const [codeSrc, setCodeSrc] = useState("Java");
  const [codeTgt, setCodeTgt] = useState("C#");
  const [codeInput, setCodeInput] = useState("");
  const [codeResult, setCodeResult] = useState<CodeComparison | null>(null);
  const [codeLoading, setCodeLoading] = useState(false);
  const [codeError, setCodeError] = useState("");

  useEffect(() => {
    fetch(`${API_URL}/api/tech/catalog`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: Catalog) => setCatalog(data))
      .catch(() => setCatalog(null));
  }, []);

  async function postJson<T>(path: string, body: unknown): Promise<T> {
    const res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
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
  }

  async function runConcept() {
    if (!concept.trim() || !srcTech || !tgtTech) return;
    setConceptLoading(true);
    setConceptError("");
    setConceptResult(null);
    try {
      const result = await postJson<ConceptComparison>("/api/compare/concept", {
        source_tech: srcTech,
        source_version: srcVer || undefined,
        target_tech: tgtTech,
        target_version: tgtVer || undefined,
        concept: concept.trim(),
      });
      setConceptResult(result);
    } catch (err) {
      setConceptError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setConceptLoading(false);
    }
  }

  async function runMapping() {
    setMapLoading(true);
    setMapError("");
    setMapRows(null);
    try {
      const result = await postJson<{ rows: MappingRow[] }>(
        "/api/compare/mapping",
        { source_stack: srcStack, target_stack: tgtStack }
      );
      setMapRows(result.rows);
    } catch (err) {
      setMapError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setMapLoading(false);
    }
  }

  async function runCode() {
    if (!codeInput.trim() || !codeSrc || !codeTgt) return;
    setCodeLoading(true);
    setCodeError("");
    setCodeResult(null);
    try {
      const result = await postJson<CodeComparison>("/api/compare/code", {
        source_tech: codeSrc,
        target_tech: codeTgt,
        source_code: codeInput,
      });
      setCodeResult(result);
    } catch (err) {
      setCodeError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setCodeLoading(false);
    }
  }

  return (
    <div className="page page--wide">
      <header className="header">
        <div className="header-title">Compare Technologies</div>
        {!catalog && <span className="badge badge--amber">● catalog offline — type tech names manually</span>}
      </header>

      {/* ---- 1. Concept comparison ---- */}
      <section className="card">
        <h2>Concept comparison</h2>
        <p className="muted">
          One concept, two technologies — graded honestly, with code on both sides.
        </p>
        <div className="grid-2">
          <TechPicker
            label="Source technology"
            catalog={catalog}
            value={srcTech}
            onChange={setSrcTech}
            version={srcVer}
            onVersionChange={setSrcVer}
          />
          <TechPicker
            label="Target technology"
            catalog={catalog}
            value={tgtTech}
            onChange={setTgtTech}
            version={tgtVer}
            onVersionChange={setTgtVer}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="concept-input">
            Concept
          </label>
          <input
            id="concept-input"
            className="input"
            value={concept}
            onChange={(e) => setConcept(e.target.value)}
            placeholder="e.g. CompletableFuture"
          />
        </div>
        <button
          className="send-btn"
          type="button"
          onClick={() => void runConcept()}
          disabled={conceptLoading || !concept.trim()}
        >
          {conceptLoading ? "Comparing…" : "Compare concept"}
        </button>
        {conceptError && <p className="error">⚠️ {conceptError}</p>}
        {conceptResult && (
          <div className="result">
            <div className="result-head">
              <strong>
                {conceptResult.concept}: {conceptResult.source_technology} →{" "}
                {conceptResult.target_technology}
              </strong>
              <EquivalenceBadge value={conceptResult.equivalence} />
              <GroundingBadge
                grounded={conceptResult.grounded}
                sources={conceptResult.sources}
              />
            </div>
            <div className="grid-2">
              <div>
                <div className="label">{conceptResult.source_technology}</div>
                <CodeBlock code={conceptResult.source_implementation} />
              </div>
              <div>
                <div className="label">{conceptResult.target_technology}</div>
                <CodeBlock code={conceptResult.target_implementation} />
              </div>
            </div>
            <dl className="kv">
              <dt>Key difference</dt>
              <dd>{conceptResult.key_difference}</dd>
              {conceptResult.target_specific_improvement && (
                <>
                  <dt>Target advantage</dt>
                  <dd>{conceptResult.target_specific_improvement}</dd>
                </>
              )}
              {conceptResult.common_migration_problem && (
                <>
                  <dt>Common migration problem</dt>
                  <dd>{conceptResult.common_migration_problem}</dd>
                </>
              )}
              <dt>Recommended approach</dt>
              <dd>{renderMarkdown(conceptResult.recommended_approach)}</dd>
            </dl>
          </div>
        )}
      </section>

      {/* ---- 2. Stack mapping ---- */}
      <section className="card">
        <h2>Stack mapping</h2>
        <p className="muted">
          Map a whole source stack to a target stack, area by area.
        </p>
        <div className="grid-2">
          <div>
            <div className="label">Source stack</div>
            {STACK_FIELDS.map((f) => (
              <input
                key={`src-${f}`}
                className="input input--stack"
                value={srcStack[f] ?? ""}
                onChange={(e) =>
                  setSrcStack((s) => ({ ...s, [f]: e.target.value }))
                }
                placeholder={f}
                aria-label={`Source ${f}`}
              />
            ))}
          </div>
          <div>
            <div className="label">Target stack</div>
            {STACK_FIELDS.map((f) => (
              <input
                key={`tgt-${f}`}
                className="input input--stack"
                value={tgtStack[f] ?? ""}
                onChange={(e) =>
                  setTgtStack((s) => ({ ...s, [f]: e.target.value }))
                }
                placeholder={f}
                aria-label={`Target ${f}`}
              />
            ))}
          </div>
        </div>
        <button
          className="send-btn"
          type="button"
          onClick={() => void runMapping()}
          disabled={mapLoading}
        >
          {mapLoading ? "Mapping…" : "Map stacks"}
        </button>
        {mapError && <p className="error">⚠️ {mapError}</p>}
        {mapRows && (
          <div className="table-wrap">
            <table className="map-table">
              <thead>
                <tr>
                  <th>Source</th>
                  <th>Target</th>
                  <th>Equivalence</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {mapRows.map((row, i) => (
                  <tr key={i}>
                    <td>{row.source || "—"}</td>
                    <td>{row.target || "—"}</td>
                    <td>
                      <EquivalenceBadge value={row.equivalence} />
                    </td>
                    <td className="muted">{row.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ---- 3. Code compare ---- */}
      <section className="card">
        <h2>Code compare</h2>
        <p className="muted">
          Paste source code, see the closest equivalent side by side. The full
          four-block conversion (original / direct / idiomatic / modern) ships
          in Phase 3.
        </p>
        <div className="grid-2">
          <div className="field">
            <label className="label" htmlFor="code-src">
              Source language
            </label>
            <input
              id="code-src"
              className="input"
              value={codeSrc}
              onChange={(e) => setCodeSrc(e.target.value)}
              placeholder="e.g. Java"
            />
          </div>
          <div className="field">
            <label className="label" htmlFor="code-tgt">
              Target language
            </label>
            <input
              id="code-tgt"
              className="input"
              value={codeTgt}
              onChange={(e) => setCodeTgt(e.target.value)}
              placeholder="e.g. C#"
            />
          </div>
        </div>
        <div className="field">
          <label className="label" htmlFor="code-input">
            Source code
          </label>
          <textarea
            id="code-input"
            className="input code-input"
            rows={8}
            value={codeInput}
            onChange={(e) => setCodeInput(e.target.value)}
            placeholder="Paste source code here…"
            spellCheck={false}
          />
        </div>
        <button
          className="send-btn"
          type="button"
          onClick={() => void runCode()}
          disabled={codeLoading || !codeInput.trim()}
        >
          {codeLoading ? "Comparing…" : "Compare code"}
        </button>
        {codeError && <p className="error">⚠️ {codeError}</p>}
        {codeResult && (
          <div className="result">
            <div className="grid-2">
              <div>
                <div className="label">{codeSrc}</div>
                <CodeBlock code={codeResult.source_code} />
              </div>
              <div>
                <div className="label">{codeTgt}</div>
                <CodeBlock code={codeResult.target_code} />
              </div>
            </div>
            {codeResult.notes.length > 0 && (
              <>
                <div className="label">Differences to know</div>
                <ul className="notes">
                  {codeResult.notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
