const UI_STATE_PREFIX = "pcopylot.ui.";

function storageAvailable(): boolean {
  try {
    return typeof globalThis.sessionStorage !== "undefined";
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
    const raw = globalThis.sessionStorage.getItem(storageKey);
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
    globalThis.sessionStorage.setItem(storageKey, JSON.stringify(value));
  } catch {
    // ignore sessionStorage failures
  }
}

export const readPersistedSessionUiState = readPersistedUiState;
export const writePersistedSessionUiState = writePersistedUiState;
