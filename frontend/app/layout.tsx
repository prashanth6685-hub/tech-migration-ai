import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Tech Migration AI — Phase 1: Chat",
  description: "AI migration and learning companion — Phase 1 chat prototype",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
