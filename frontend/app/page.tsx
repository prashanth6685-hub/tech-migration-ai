"use client";

import {
  Fragment,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

type Role = "user" | "assistant";

interface Message {
  id: number;
  role: Role;
  content: string;
}

interface Health {
  status: string;
  provider: string;
  model: string;
  ollama_reachable: boolean;
}

interface ChatEvent {
  token?: string;
  done?: boolean;
  error?: string;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SUGGESTION = "Explain Java streams to me as a C# developer";

let nextId = 1;
function makeMessage(role: Role, content: string): Message {
  return { id: nextId++, role, content };
}

/* ---------- Markdown-lite renderer (no libraries, no innerHTML) ---------- */

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
function renderMarkdown(content: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  const segments = content.split("```");
  // An even number of segments means the last fence never closed — treat it as prose.
  const lastUnclosed = segments.length % 2 === 0;
  segments.forEach((segment, i) => {
    const isCode = i % 2 === 1 && !(lastUnclosed && i === segments.length - 1);
    if (isCode) {
      const lines = segment.split("\n");
      // First line may be a language tag (e.g. ```java) — drop it.
      const code =
        lines.length > 1 ? lines.slice(1).join("\n") : segment;
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

/* ---------- Health badge ---------- */

function HealthBadge({ health }: { health: Health | null }) {
  if (!health) {
    return <span className="badge badge--gray">● backend unreachable</span>;
  }
  if (health.provider === "ollama") {
    if (health.ollama_reachable) {
      return (
        <span className="badge badge--green">
          ● model ready (ollama · {health.model})
        </span>
      );
    }
    return <span className="badge badge--amber">● model unavailable</span>;
  }
  return (
    <span className="badge badge--gray">
      ● {health.provider} · {health.model}
    </span>
  );
}

/* ---------- Chat page ---------- */

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);

  const messagesRef = useRef<Message[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // Backend health check on load.
  useEffect(() => {
    let cancelled = false;
    fetch(`${API_URL}/api/health`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: Health) => {
        if (!cancelled) setHealth(data);
      })
      .catch(() => {
        if (!cancelled) setHealth(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Auto-scroll to bottom on new content.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, streaming]);

  async function send(rawText: string) {
    const text = rawText.trim();
    if (!text || streaming) return;

    const userMsg = makeMessage("user", text);
    const assistantMsg = makeMessage("assistant", "");
    const history = [...messagesRef.current, userMsg];

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: history.map((m) => ({
            role: m.role,
            content: m.content,
          })),
        }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        throw new Error(`Backend responded with HTTP ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let streamDone = false;

      while (!streamDone) {
        const { value, done: readerDone } = await reader.read();
        if (readerDone) break;
        buffer += decoder.decode(value, { stream: true });

        // Pull complete lines out of the buffer (a chunk may split mid-line).
        let newlineIndex: number;
        while ((newlineIndex = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, newlineIndex).trim();
          buffer = buffer.slice(newlineIndex + 1);
          if (!line.startsWith("data:")) continue;

          const payload = line.slice("data:".length).trim();
          if (!payload) continue;

          let event: ChatEvent;
          try {
            event = JSON.parse(payload) as ChatEvent;
          } catch {
            continue; // ignore malformed lines
          }

          if (event.token) {
            const token = event.token;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantMsg.id
                  ? { ...m, content: m.content + token }
                  : m
              )
            );
          } else if (event.error) {
            throw new Error(event.error);
          } else if (event.done) {
            streamDone = true;
            break;
          }
        }
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        const detail =
          err instanceof Error ? err.message : "Unknown error";
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantMsg.id
              ? {
                  ...m,
                  content: `⚠️ Could not get a response: ${detail}. Make sure the backend is running and try again.`,
                }
              : m
          )
        );
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  function clearChat() {
    abortRef.current?.abort();
    setMessages([]);
    setInput("");
    inputRef.current?.focus();
  }

  function tapSuggestion() {
    setInput(SUGGESTION);
    inputRef.current?.focus();
  }

  return (
    <div className="page">
      <header className="header">
        <div className="header-title">Tech Migration AI — Phase 1: Chat</div>
        <HealthBadge health={health} />
        <button className="clear-btn" onClick={clearChat} type="button">
          Clear chat
        </button>
      </header>

      <div className="chat-list" ref={listRef} aria-live="polite">
        {messages.map((m, idx) =>
          m.role === "user" ? (
            <div key={m.id} className="message message--user">
              <div className="bubble">{m.content}</div>
            </div>
          ) : (
            <div key={m.id} className="message message--assistant">
              <div className="bubble">
                {m.content === "" && streaming ? (
                  <span className="thinking">Thinking…</span>
                ) : (
                  <>
                    {renderMarkdown(m.content)}
                    {streaming && idx === messages.length - 1 && (
                      <span className="cursor" aria-hidden="true" />
                    )}
                  </>
                )}
              </div>
            </div>
          )
        )}
      </div>

      <div className="suggestion-row">
        <button
          className="chip"
          type="button"
          onClick={tapSuggestion}
          disabled={streaming}
        >
          💡 {SUGGESTION}
        </button>
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <textarea
          ref={inputRef}
          className="input"
          rows={2}
          value={input}
          disabled={streaming}
          placeholder="Ask about your migration…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send(input);
            }
          }}
          aria-label="Chat message"
        />
        <button
          className="send-btn"
          type="submit"
          disabled={streaming || !input.trim()}
        >
          Send
        </button>
      </form>
    </div>
  );
}
