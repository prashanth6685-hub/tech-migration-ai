"use client";

import { useCallback, useEffect, useState } from "react";

import type { Catalog } from "../../components/tech-picker";
import { TechPicker } from "../../components/tech-picker";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface CollectionSummary {
  name: string;
  chunks: number;
}

interface IngestResponse {
  collection: string;
  chunks_ingested: number;
  items: number;
  errors: string[];
}

const DOC_TYPES = [
  { id: "official", label: "Official documentation" },
  { id: "guide", label: "Migration guide" },
  { id: "api_reference", label: "API reference" },
] as const;

export default function KnowledgePage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [urls, setUrls] = useState("");
  const [tech, setTech] = useState("C#");
  const [version, setVersion] = useState(".NET 8");
  const [docType, setDocType] = useState<string>("official");
  const [ingesting, setIngesting] = useState(false);
  const [ingestResult, setIngestResult] = useState<IngestResponse | null>(null);
  const [error, setError] = useState("");
  const [collections, setCollections] = useState<CollectionSummary[]>([]);
  const [deleting, setDeleting] = useState<string | null>(null);

  const loadCollections = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/knowledge/collections`);
      if (res.ok) setCollections((await res.json()) as CollectionSummary[]);
    } catch {
      /* backend offline — leave the table empty */
    }
  }, []);

  useEffect(() => {
    fetch(`${API_URL}/api/tech/catalog`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: Catalog | null) => setCatalog(data))
      .catch(() => setCatalog(null));
    void loadCollections();
  }, [loadCollections]);

  async function runIngest() {
    const lines = urls
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 0);
    if (lines.length === 0 || !tech || ingesting) return;
    setIngesting(true);
    setError("");
    setIngestResult(null);
    try {
      const res = await fetch(`${API_URL}/api/knowledge/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          items: lines.map((url) => ({ url })),
          tech,
          version: version || undefined,
          doc_type: docType,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(
          typeof err.detail === "string" ? err.detail : `HTTP ${res.status}`
        );
      }
      setIngestResult((await res.json()) as IngestResponse);
      setUrls("");
      await loadCollections();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed");
    } finally {
      setIngesting(false);
    }
  }

  async function deleteCollection(name: string) {
    if (deleting) return;
    setDeleting(name);
    try {
      const res = await fetch(
        `${API_URL}/api/knowledge/collections/${encodeURIComponent(name)}`,
        { method: "DELETE" }
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await loadCollections();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="page">
      <header className="header">
        <div className="header-title">Knowledge Base</div>
      </header>

      <section className="card">
        <h2>Ingest documentation</h2>
        <p className="muted">
          Paste official documentation URLs (one per line). Pages are fetched,
          cleaned, chunked, embedded locally, and stored — answers about this
          technology are then grounded in them. Re-ingesting a URL replaces its
          old chunks.
        </p>
        <div className="grid-2">
          <TechPicker
            label="Technology"
            catalog={catalog}
            value={tech}
            onChange={setTech}
            version={version}
            onVersionChange={setVersion}
          />
          <div className="field">
            <label className="label" htmlFor="doc-type">
              Document type
            </label>
            <select
              id="doc-type"
              className="input"
              value={docType}
              onChange={(e) => setDocType(e.target.value)}
            >
              {DOC_TYPES.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="field">
          <label className="label" htmlFor="doc-urls">
            Documentation URLs
          </label>
          <textarea
            id="doc-urls"
            className="input code-input"
            value={urls}
            onChange={(e) => setUrls(e.target.value)}
            placeholder={"https://learn.microsoft.com/en-us/ef/core/\nhttps://learn.microsoft.com/en-us/aspnet/core/fundamentals/"}
            spellCheck={false}
          />
        </div>
        <button
          className="send-btn"
          type="button"
          onClick={() => void runIngest()}
          disabled={ingesting || !urls.trim() || !tech}
        >
          {ingesting ? "Ingesting… (this can take a minute)" : "Ingest"}
        </button>
        {error && <p className="error">⚠️ {error}</p>}
        {ingestResult && (
          <div className="result">
            <p>
              ✅ <strong>{ingestResult.chunks_ingested}</strong> chunks ingested
              into <code>{ingestResult.collection}</code> from{" "}
              {ingestResult.items} URL{ingestResult.items === 1 ? "" : "s"}.
            </p>
            {ingestResult.errors.length > 0 && (
              <ul className="expl-list">
                {ingestResult.errors.map((e, i) => (
                  <li key={i}>⚠️ {e}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      <section className="card">
        <h2>Collections</h2>
        {collections.length === 0 ? (
          <p className="muted">
            No documentation ingested yet. Answers will carry an “ungrounded”
            marker until you ingest some.
          </p>
        ) : (
          <table className="map-table">
            <thead>
              <tr>
                <th>Collection</th>
                <th>Chunks</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {collections.map((c) => (
                <tr key={c.name}>
                  <td>
                    <code>{c.name}</code>
                  </td>
                  <td>{c.chunks}</td>
                  <td>
                    <button
                      type="button"
                      className="clear-btn"
                      onClick={() => void deleteCollection(c.name)}
                      disabled={deleting === c.name}
                    >
                      {deleting === c.name ? "Deleting…" : "Delete"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
