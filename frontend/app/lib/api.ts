/** Backend base URL, env-driven with a local fallback.
 *
 * NEXT_PUBLIC_API_URL may be a full URL ("https://api.example.com") or a
 * bare Render host ("tech-migration-ai-backend.onrender.com") — the latter
 * gets an https:// scheme. Trailing slashes are stripped.
 */
function resolveApiUrl(): string {
  const raw = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
    .trim()
    .replace(/\/+$/, "");
  if (!raw) return "http://localhost:8000";
  return /^https?:\/\//i.test(raw) ? raw : `https://${raw}`;
}

export const API_URL: string = resolveApiUrl();
