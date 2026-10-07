"use client";

import { Fragment, type ReactNode } from "react";

/** Render **bold** within a line; text nodes are auto-escaped by React. */
function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  text.split("\n").forEach((line, li) => {
    if (li > 0) nodes.push(<br key={`br-${li}`} />);
    line.split(/(\*\*[^*]+\*\*)/g).forEach((part, k) => {
      const m = /^\*\*([^*]+)\*\*$/.exec(part);
      if (m) {
        nodes.push(<strong key={`b-${li}-${k}`}>{m[1]}</strong>);
      } else {
        nodes.push(<Fragment key={`t-${li}-${k}`}>{part}</Fragment>);
      }
    });
  });
  return nodes;
}

/** Render ```code fences as <pre><code>, paragraphs otherwise. */
export function renderMarkdown(content: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const segments = content.split("```");
  // An even number of segments means the last fence never closed — treat it as prose.
  const lastUnclosed = segments.length % 2 === 0;
  segments.forEach((segment, i) => {
    const isCode = i % 2 === 1 && !(lastUnclosed && i === segments.length - 1);
    if (isCode) {
      const lines = segment.split("\n");
      // First line may be a language tag (e.g. ```java) — drop it.
      const code = lines.length > 1 ? lines.slice(1).join("\n") : segment;
      nodes.push(
        <pre key={`code-${i}`} className="code-block">
          <code>{code.replace(/^\n+|\n+$/g, "")}</code>
        </pre>
      );
      return;
    }
    segment.split(/\n{2,}/).forEach((para, j) => {
      if (!para.trim()) return;
      nodes.push(<p key={`p-${i}-${j}`}>{renderInline(para)}</p>);
    });
  });
  return nodes;
}
