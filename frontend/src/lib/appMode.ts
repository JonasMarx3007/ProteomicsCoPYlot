export type AppMode = "analysis" | "viewer";

function parseMode(raw: string | undefined): AppMode {
  if (!raw) return "analysis";
  return raw.trim().toLowerCase() === "viewer" ? "viewer" : "analysis";
}

function parseFlag(raw: string | undefined): boolean {
  if (!raw) return false;
  const normalized = raw.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

export const APP_MODE: AppMode = parseMode(import.meta.env.VITE_APP_MODE);
export const IS_VIEWER_MODE = APP_MODE === "viewer";
export const IS_AI_MODE = parseFlag(import.meta.env.VITE_AI_ENABLED);
