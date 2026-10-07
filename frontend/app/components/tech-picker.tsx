"use client";

import { useMemo, useState } from "react";

export interface TechEntry {
  id: string;
  name: string;
  versions: string[];
}

export interface Catalog {
  [category: string]: TechEntry[];
}

const OTHER = "__other__";

interface TechPickerProps {
  label: string;
  catalog: Catalog | null;
  value: string;
  onChange: (v: string) => void;
  version: string;
  onVersionChange: (v: string) => void;
}

/** Technology picker: catalog select with free-text fallback + version datalist. */
export function TechPicker({
  label,
  catalog,
  value,
  onChange,
  version,
  onVersionChange,
}: TechPickerProps) {
  const [custom, setCustom] = useState(false);

  const groups = useMemo(() => {
    if (!catalog) return [];
    const wanted = ["languages", "frameworks", "orms", "testing", "databases", "runtimes", "build"];
    return wanted
      .filter((c) => catalog[c])
      .map((c) => ({ category: c, entries: catalog[c] }));
  }, [catalog]);

  const versions = useMemo(() => {
    if (!catalog || custom) return [];
    for (const entries of Object.values(catalog)) {
      const found = entries.find((e) => e.name === value);
      if (found) return found.versions;
    }
    return [];
  }, [catalog, custom, value]);

  return (
    <div className="field">
      <label className="label">{label}</label>
      {!custom ? (
        <select
          className="select"
          value={value}
          onChange={(e) => {
            if (e.target.value === OTHER) {
              setCustom(true);
              onChange("");
            } else {
              onChange(e.target.value);
            }
          }}
          aria-label={label}
        >
          <option value="" disabled>
            Select…
          </option>
          {groups.map((g) => (
            <optgroup key={g.category} label={g.category}>
              {g.entries.map((t) => (
                <option key={t.id} value={t.name}>
                  {t.name}
                </option>
              ))}
            </optgroup>
          ))}
          <option value={OTHER}>Other… (type your own)</option>
        </select>
      ) : (
        <div className="field-row">
          <input
            className="input"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="e.g. Kotlin"
            aria-label={`${label} (custom)`}
          />
          <button
            type="button"
            className="link-btn"
            onClick={() => {
              setCustom(false);
              onChange("");
            }}
          >
            catalog
          </button>
        </div>
      )}
      <input
        className="input input--version"
        value={version}
        onChange={(e) => onVersionChange(e.target.value)}
        placeholder="Version (optional)"
        list={`versions-${label.replace(/\s+/g, "-")}`}
        aria-label={`${label} version`}
      />
      {versions.length > 0 && (
        <datalist id={`versions-${label.replace(/\s+/g, "-")}`}>
          {versions.map((v) => (
            <option key={v} value={v} />
          ))}
        </datalist>
      )}
    </div>
  );
}
