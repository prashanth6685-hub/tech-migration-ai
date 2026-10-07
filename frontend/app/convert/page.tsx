"use client";

import { useEffect, useState } from "react";

import type { Catalog } from "../components/tech-picker";
import { TechPicker } from "../components/tech-picker";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type Equivalence = "exact" | "conceptual" | "partial" | "none";

interface ConversionExplanation {
  what_changed: string[];
  why_changed: string[];
  target_differences: string;
  new_capabilities: string[];
  performance_notes: string;
  common_mistakes: string[];
  modern_note: string;
}

interface CodeConversion {
  source_code: string;
  direct_translation: string;
  idiomatic_target: string;
  modern_target: string;
  equivalence: Equivalence;
  explanation: ConversionExplanation;
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

const JAVA_EXAMPLE = `List<Employee> result = new ArrayList<>();
for (Employee employee : employees) {
    if (employee.getAge() > 30) {
        result.add(employee);
    }
}`;

function EquivalenceBadge({ value }: { value: Equivalence }) {
  return (
    <span className={`badge ${EQUIV_BADGE[value]}`}>● {EQUIV_LABEL[value]}</span>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Fallback for browsers without async clipboard.
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

export default function ConvertPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [srcTech, setSrcTech] = useState("Java");
  const [srcVer, setSrcVer] = useState("17");
  const [tgtTech, setTgtTech] = useState("C#");
  const [tgtVer, setTgtVer] = useState(".NET 8");
  const [styleHint, setStyleHint] = useState("");
  const [codeInput, setCodeInput] = useState("");
  const [result, setResult] = useState<CodeConversion | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [rawOutput, setRawOutput] = useState("");

  useEffect(() => {
    fetch(`${API_URL}/api/tech/catalog`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data: Catalog) => setCatalog(data))
      .catch(() => setCatalog(null));
  }, []);

  async function runConvert() {
    if (!codeInput.trim() || !srcTech || !tgtTech || loading) return;
    setLoading(true);
    setError("");
    setRawOutput("");
    setResult(null);
    try {
      const res = await fetch(`${API_URL}/api/convert`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_tech: srcTech,
          source_version: srcVer || undefined,
          target_tech: tgtTech,
          target_version: tgtVer || undefined,
          style_hint: styleHint.trim() || undefined,
          source_code: codeInput,
        }),
      });
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        let raw = "";
        try {
          const err = await res.json();
          detail = err.detail?.error ?? detail;
          raw = err.detail?.raw ?? "";
        } catch {
          /* keep default */
        }
        if (raw) setRawOutput(raw);
        throw new Error(detail);
      }
      setResult((await res.json()) as CodeConversion);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  }

  const expl = result?.explanation;

  return (
    <div className="page page--wide">
      <header className="header">
        <div className="header-title">Convert Code</div>
        {!catalog && (
          <span className="badge badge--amber">
            ● catalog offline — type tech names manually
          </span>
        )}
      </header>

      <section className="card">
        <h2>Code conversion</h2>
        <p className="muted">
          Paste code, pick the target — get the original, a direct translation,
          the idiomatic version, and the modern version, with an explanation.
        </p>
        <div className="grid-2">
          <TechPicker
            label="Source language"
            catalog={catalog}
            value={srcTech}
            onChange={setSrcTech}
            version={srcVer}
            onVersionChange={setSrcVer}
          />
          <TechPicker
            label="Target language"
            catalog={catalog}
            value={tgtTech}
            onChange={setTgtTech}
            version={tgtVer}
            onVersionChange={setTgtVer}
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="style-hint">
            Style hint <span className="muted">(optional)</span>
          </label>
          <input
            id="style-hint"
            className="input"
            value={styleHint}
            onChange={(e) => setStyleHint(e.target.value)}
            placeholder="e.g. spring-controller, junit-test"
          />
        </div>
        <div className="field">
          <label className="label" htmlFor="code-input">
            Source code
          </label>
          <textarea
            id="code-input"
            className="input code-input"
            value={codeInput}
            onChange={(e) => setCodeInput(e.target.value)}
            placeholder="Paste source code here…"
            spellCheck={false}
          />
        </div>
        <div className="suggestion-row">
          <button
            type="button"
            className="chip"
            onClick={() => setCodeInput(JAVA_EXAMPLE)}
            disabled={loading}
          >
            💡 Try the Java → C# example
          </button>
        </div>
        <button
          className="send-btn"
          type="button"
          onClick={() => void runConvert()}
          disabled={loading || !codeInput.trim() || !srcTech || !tgtTech}
        >
          {loading ? "Converting…" : "Convert"}
        </button>
        {error && <p className="error">⚠️ {error}</p>}
        {rawOutput && (
          <div>
            <p className="muted">
              The model returned output that wasn&apos;t valid JSON. Raw text
              below — you can retry.
            </p>
            <pre className="code-block">
              <code>{rawOutput}</code>
            </pre>
          </div>
        )}
        {result && (
          <div className="result">
            <div className="result-head">
              <strong>
                {srcTech}
                {srcVer ? ` ${srcVer}` : ""} → {tgtTech}
                {tgtVer ? ` ${tgtVer}` : ""}
              </strong>
              <EquivalenceBadge value={result.equivalence} />
            </div>
            <CodeBlock title="1. Original" code={result.source_code} />
            <CodeBlock title="2. Direct translation" code={result.direct_translation} />
            <CodeBlock title="3. Idiomatic target" code={result.idiomatic_target} />
            <CodeBlock title="4. Modern target" code={result.modern_target} />
            {expl && (
              <>
                <h3>Explanation</h3>
                <dl className="kv">
                  <dt>What changed</dt>
                  <dd>
                    <ul className="expl-list">
                      {expl.what_changed.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </dd>
                  <dt>Why it changed</dt>
                  <dd>
                    <ul className="expl-list">
                      {expl.why_changed.map((s, i) => (
                        <li key={i}>{s}</li>
                      ))}
                    </ul>
                  </dd>
                  <dt>What the target does differently</dt>
                  <dd>{expl.target_differences}</dd>
                  {expl.new_capabilities.length > 0 && (
                    <>
                      <dt>New capabilities</dt>
                      <dd>
                        <ul className="expl-list">
                          {expl.new_capabilities.map((s, i) => (
                            <li key={i}>{s}</li>
                          ))}
                        </ul>
                      </dd>
                    </>
                  )}
                  {expl.performance_notes && (
                    <>
                      <dt>Performance</dt>
                      <dd>{expl.performance_notes}</dd>
                    </>
                  )}
                  {expl.common_mistakes.length > 0 && (
                    <>
                      <dt>Common mistakes</dt>
                      <dd>
                        <ul className="expl-list">
                          {expl.common_mistakes.map((s, i) => (
                            <li key={i}>{s}</li>
                          ))}
                        </ul>
                      </dd>
                    </>
                  )}
                  {expl.modern_note && (
                    <>
                      <dt>On the modern version</dt>
                      <dd>{expl.modern_note}</dd>
                    </>
                  )}
                </dl>
              </>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
