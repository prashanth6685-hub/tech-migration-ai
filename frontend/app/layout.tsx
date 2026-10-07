import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tech Migration AI",
  description: "An AI migration and learning companion that understands what you already know",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <nav className="topnav" aria-label="Main">
          <a href="/">💬 Chat</a>
          <a href="/compare">🔀 Compare</a>
          <a href="/convert">🔄 Convert</a>
          <a href="/learn">🎓 Learn</a>
          <a href="/migrate">🗂️ Migrate</a>
        </nav>
        {children}
        <footer className="site-footer">
          <a href="/admin/knowledge">📚 Knowledge base</a>
          <span className="muted"> — ingest official docs to ground answers</span>
        </footer>
      </body>
    </html>
  );
}
