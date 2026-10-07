"use client";

import { useCallback, useEffect, useState } from "react";
import { API_URL } from "../lib/api";


type FileStatus = "untouched" | "pending" | "approved" | "rejected";
type Equivalence = "exact" | "conceptual" | "partial" | "none";
type Risk = "low" | "medium" | "high";

interface ProjectFile {
  path: string;
  size: number;
  language: string;
  status: FileStatus;
}

interface FileConversion {
  path: string;
  status: FileStatus;
  original: string;
  proposed: string;
  explanation: string;
  equivalence: Equivalence;
  risk: Risk;
  risk_why: string;
  warnings: string[];
}

interface GeneratedTests {
  path: string;
  status: FileStatus;
  source_path: string;
  test_code: string;
  framework: string;
  notes: string;
  warnings: string[];
}

const STATUS_BADGE: Record<FileStatus, string> = {
  untouched: "badge--gray",
  pending: "badge--amber",
  approved: "badge--green",
  rejected: "badge--red",
};

const RISK_BADGE: Record<Risk, string> = {
  low: "badge--green",
  medium: "badge--amber",
  high: "badge--red",
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
    <button type="button" className="copy-btn" onClick={() => void copy()}>
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

export function ReviewSection({ projectId }: { projectId: string }) {
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [conversion, setConversion] = useState<FileConversion | null>(null);
  const [tests, setTests] = useState<GeneratedTests | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadFiles = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/migration/${projectId}/files`);
      if (res.ok) setFiles((await res.json()) as ProjectFile[]);
    } catch {
      /* leave as-is */
    }
  }, [projectId]);

  useEffect(() => {
    void loadFiles();
  }, [loadFiles]);

  async function postJson<T>(url: string, body: unknown): Promise<T> {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const detail = err.detail;
      throw new Error(
        typeof detail === "string" ? detail : detail?.error ?? `HTTP ${res.status}`
      );
    }
    return (await res.json()) as T;
  }

  async function openFile(path: string) {
    setSelected(path);
    setConversion(null);
    setTests(null);
    setError("");
    setBusy(true);
    try {
      const conv = await postJson<FileConversion>(
        `${API_URL}/api/migration/convert-file`,
        { project_id: projectId, path }
      );
      setConversion(conv);
      await loadFiles();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Conversion failed");
    } finally {
      setBusy(false);
    }
  }

  async function decide(path: string, approved: boolean) {
    setBusy(true);
    setError("");
    try {
      await postJson(`${API_URL}/api/migration/approve`, {
        project_id: projectId,
        path,
        approved,
      });
      if (conversion && conversion.path === path) {
        setConversion({ ...conversion, status: approved ? "approved" : "rejected" });
      }
      if (tests && tests.path === path) {
        setTests({ ...tests, status: approved ? "approved" : "rejected" });
      }
      await loadFiles();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision failed");
    } finally {
      setBusy(false);
    }
  }

  async function generateTests() {
    if (!selected || busy) return;
    setBusy(true);
    setError("");
    try {
      const gen = await postJson<GeneratedTests>(
        `${API_URL}/api/migration/generate-tests`,
        { project_id: projectId, path: selected }
      );
      setTests(gen);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test generation failed");
    } finally {
      setBusy(false);
    }
  }

  const approved = files.filter((f) => f.status === "approved").length;

  return (
    <section className="card">
      <div className="result-head">
        <h2>4. Review &amp; migrate — human approval</h2>
        {files.length > 0 && (
          <span className="muted">
            {approved} of {files.length} files approved
          </span>
        )}
      </div>
      <p className="muted">
        Every proposed change needs your approval. Nothing is written anywhere
        until you approve it — approved output goes to a separate migrated
        tree; your upload is never modified.
      </p>
      {files.length > 0 && (
        <ScoreProgress value={approved} total={files.length} />
      )}
      {error && <p className="error">⚠️ {error}</p>}

      <table className="map-table">
        <thead>
          <tr>
            <th>File</th>
            <th>Language</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {files.map((f) => (
            <tr key={f.path}>
              <td>
                <code>{f.path}</code>
              </td>
              <td>{f.language}</td>
              <td>
                <span className={`badge ${STATUS_BADGE[f.status]}`}>
                  {f.status}
                </span>
              </td>
              <td>
                <button
                  type="button"
                  className="clear-btn"
                  onClick={() => void openFile(f.path)}
                  disabled={busy}
                >
                  {f.status === "untouched" ? "Convert" : "Review"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {files.length === 0 && (
        <p className="muted">No convertible source files found in this project.</p>
      )}

      {busy && !conversion && <p className="muted">Working…</p>}

      {conversion && (
        <div className="result">
          <div className="result-head">
            <strong>
                <code>{conversion.path}</code>
              </strong>
            <span className={`badge ${STATUS_BADGE[conversion.status]}`}>
              {conversion.status}
            </span>
            <span className={`badge ${RISK_BADGE[conversion.risk]}`}>
              risk: {conversion.risk}
            </span>
          </div>
          <p className="muted">
            <strong>Risk:</strong> {conversion.risk_why}
          </p>
          {conversion.warnings.length > 0 && (
            <div className="warn-box">
              <strong>
                ⚠️ Heuristic checks (not a compiler — review carefully):
              </strong>
              <ul className="expl-list">
                {conversion.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="grid-2">
            <CodeBlock title="Original" code={conversion.original} />
            <CodeBlock title="Proposed (idiomatic target)" code={conversion.proposed} />
          </div>
          <dl className="kv">
            <dt>Explanation</dt>
            <dd>{conversion.explanation}</dd>
          </dl>
          <div className="decision-row">
            <button
              type="button"
              className="send-btn"
              onClick={() => void decide(conversion.path, true)}
              disabled={busy || conversion.status === "approved"}
            >
              ✓ Approve
            </button>
            <button
              type="button"
              className="clear-btn"
              onClick={() => void decide(conversion.path, false)}
              disabled={busy || conversion.status === "rejected"}
            >
              ✕ Reject
            </button>
            <button
              type="button"
              className="clear-btn"
              onClick={() => void generateTests()}
              disabled={busy}
            >
              🧪 Generate tests
            </button>
          </div>

          {tests && (
            <div className="result">
              <div className="result-head">
                <strong>
                  Tests: <code>{tests.path}</code> ({tests.framework})
                </strong>
                <span className={`badge ${STATUS_BADGE[tests.status]}`}>
                  {tests.status}
                </span>
              </div>
              {tests.notes && <p className="muted">{tests.notes}</p>}
              {tests.warnings.length > 0 && (
                <div className="warn-box">
                  <strong>⚠️ Heuristic checks (not a compiler):</strong>
                  <ul className="expl-list">
                    {tests.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}
              <CodeBlock title="Generated tests" code={tests.test_code} />
              <div className="decision-row">
                <button
                  type="button"
                  className="send-btn"
                  onClick={() => void decide(tests.path, true)}
                  disabled={busy || tests.status === "approved"}
                >
                  ✓ Approve tests
                </button>
                <button
                  type="button"
                  className="clear-btn"
                  onClick={() => void decide(tests.path, false)}
                  disabled={busy || tests.status === "rejected"}
                >
                  ✕ Reject
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {approved > 0 && (
        <p>
          <a
            className="send-btn"
            href={`${API_URL}/api/migration/${projectId}/download`}
          >
            ⬇ Download approved files (.zip)
          </a>
        </p>
      )}
    </section>
  );
}

function ScoreProgress({ value, total }: { value: number; total: number }) {
  const pct = total === 0 ? 0 : Math.round((value / total) * 100);
  return (
    <div className="score-row">
      <span className="score-label">Progress</span>
      <div className="score-track">
        <div
          className="score-fill"
          style={{ width: `${pct}%`, background: "var(--blue)" }}
        />
      </div>
      <span className="score-value">{pct}%</span>
    </div>
  );
}
