"use client";

export interface Citation {
  title: string;
  url: string;
}

/**
 * Phase 5 grounding badge. Shows whether an answer was grounded in
 * ingested official documentation (with expandable source links) or came
 * from model knowledge alone.
 */
export function GroundingBadge({
  grounded,
  sources,
}: {
  grounded?: boolean;
  sources?: Citation[];
}) {
  const list = sources ?? [];
  if (grounded) {
    return (
      <span className="badge badge--green">
        📚 Grounded in official docs
        {list.length > 0 && (
          <details className="sources-details">
            <summary>
              {list.length} source{list.length === 1 ? "" : "s"}
            </summary>
            <ul>
              {list.map((s, i) => (
                <li key={i}>
                  {s.url ? (
                    <a href={s.url} target="_blank" rel="noreferrer">
                      {s.title || s.url}
                    </a>
                  ) : (
                    <span>{s.title}</span>
                  )}
                </li>
              ))}
            </ul>
          </details>
        )}
      </span>
    );
  }
  return (
    <span
      className="badge badge--gray"
      title="No relevant documentation is ingested yet — this answer comes from the model's own knowledge."
    >
      ⚠️ From model knowledge — not yet grounded
    </span>
  );
}
