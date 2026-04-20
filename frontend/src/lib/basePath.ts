const BASE_URL = String(import.meta.env.BASE_URL || "/");

function normalizedBaseUrl(): string {
  if (!BASE_URL) return "/";
  return BASE_URL.endsWith("/") ? BASE_URL : `${BASE_URL}/`;
}

export function withBasePath(path: string): string {
  const raw = String(path || "").trim();
  if (!raw) return normalizedBaseUrl();
  if (/^(https?:|data:|blob:)/i.test(raw)) return raw;
  const suffix = raw.startsWith("/") ? raw.slice(1) : raw;
  return `${normalizedBaseUrl()}${suffix}`;
}

