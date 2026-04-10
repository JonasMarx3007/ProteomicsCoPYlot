const UI_STATE_PREFIX = "pcopylot.ui.";

function storageAvailable(): boolean {
  try {
    return typeof globalThis.localStorage !== "undefined";
  } catch {
    return false;
  }
}

function fullKey(key: string): string {
  const normalized = String(key || "").trim();
  return normalized.startsWith(UI_STATE_PREFIX) ? normalized : `${UI_STATE_PREFIX}${normalized}`;
}

export function readPersistedUiState<T>(key: string, fallback: T): T {
  if (!storageAvailable()) return fallback;
  const storageKey = fullKey(key);
  try {
    const raw = globalThis.localStorage.getItem(storageKey);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as T;
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

export function writePersistedUiState(key: string, value: unknown): void {
  if (!storageAvailable()) return;
  const storageKey = fullKey(key);
  try {
    globalThis.localStorage.setItem(storageKey, JSON.stringify(value));
  } catch {
    // ignore localStorage failures
  }
}

export function clearPersistedUiState(key: string): void {
  if (!storageAvailable()) return;
  const storageKey = fullKey(key);
  try {
    globalThis.localStorage.removeItem(storageKey);
  } catch {
    // ignore localStorage failures
  }
}

