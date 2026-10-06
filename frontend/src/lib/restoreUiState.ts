const ANALYSIS_STORAGE_PREFIXES = ["pcopylot.report.", "pcopylot.ui.", "copylot:advanced"] as const;

function removeCopylotKeys(storage: Storage): void {
  const keysToRemove: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (!key) continue;
    if (ANALYSIS_STORAGE_PREFIXES.some((prefix) => key.startsWith(prefix))) {
      keysToRemove.push(key);
    }
  }
  for (const key of keysToRemove) {
    storage.removeItem(key);
  }
}

export function clearCopylotClientStorageState(): void {
  try {
    if (typeof globalThis.sessionStorage !== "undefined") {
      removeCopylotKeys(globalThis.sessionStorage);
    }
  } catch {}
}

export function captureCopylotSessionStorageState(): Record<string, string | null> {
  try {
    if (typeof globalThis.sessionStorage === "undefined") return {};
    const payload: Record<string, string | null> = {};
    for (let index = 0; index < globalThis.sessionStorage.length; index += 1) {
      const key = globalThis.sessionStorage.key(index);
      if (!key) continue;
      if (!ANALYSIS_STORAGE_PREFIXES.some((prefix) => key.startsWith(prefix))) continue;
      payload[key] = globalThis.sessionStorage.getItem(key);
    }
    return payload;
  } catch {
    return {};
  }
}

export function applyCopylotSessionStorageState(
  payload: Record<string, unknown> | null | undefined
): void {
  try {
    if (typeof globalThis.sessionStorage === "undefined") return;
    const entries = payload && typeof payload === "object" ? payload : {};
    removeCopylotKeys(globalThis.sessionStorage);
    for (const [key, raw] of Object.entries(entries)) {
      if (!ANALYSIS_STORAGE_PREFIXES.some((prefix) => key.startsWith(prefix))) continue;
      if (typeof raw === "string") globalThis.sessionStorage.setItem(key, raw);
    }
  } catch {}
}
