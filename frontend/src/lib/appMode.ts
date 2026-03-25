export type AppMode = "analysis" | "viewer";

function parseMode(raw: string | undefined): AppMode {
  if (!raw) return "analysis";
  return raw.trim().toLowerCase() === "viewer" ? "viewer" : "analysis";
}

export const APP_MODE: AppMode = parseMode(import.meta.env.VITE_APP_MODE);
export const IS_VIEWER_MODE = APP_MODE === "viewer";
