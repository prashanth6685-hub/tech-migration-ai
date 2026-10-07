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
        </nav>
        {children}
      </body>
    </html>
  );
}
