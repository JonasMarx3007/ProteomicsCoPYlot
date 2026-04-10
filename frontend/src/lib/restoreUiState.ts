export const REPORT_LOCAL_STORAGE_KEYS = [
  "pcopylot.report.qcSettings.v1",
  "pcopylot.report.volcanoLog.v1",
  "pcopylot.report.datasetScope.v1",
] as const;
const COPYLOT_LOCAL_STORAGE_PREFIXES = ["pcopylot.report.", "pcopylot.ui."] as const;

export type AppUiStateSnapshot = {
  version: 1;
  app?: Record<string, unknown>;
  reportLocalStorage?: Record<string, string | null>;
};

function hasLocalStorage(): boolean {
  try {
    return typeof globalThis.localStorage !== "undefined";
  } catch {
    return false;
  }
}

export function captureReportLocalStorageState(): Record<string, string | null> {
  if (!hasLocalStorage()) return {};
  const payload: Record<string, string | null> = {};
  for (const key of REPORT_LOCAL_STORAGE_KEYS) {
    try {
      payload[key] = globalThis.localStorage.getItem(key);
    } catch {
      payload[key] = null;
    }
  }
  return payload;
}

export function captureCopylotLocalStorageState(): Record<string, string | null> {
  if (!hasLocalStorage()) return {};
  const payload: Record<string, string | null> = {};
  try {
    for (let index = 0; index < globalThis.localStorage.length; index += 1) {
      const key = globalThis.localStorage.key(index);
      if (!key) continue;
      if (!COPYLOT_LOCAL_STORAGE_PREFIXES.some((prefix) => key.startsWith(prefix))) continue;
      payload[key] = globalThis.localStorage.getItem(key);
    }
  } catch {
    // ignore enumeration failures
  }
  return payload;
}

export function applyReportLocalStorageState(
  payload: Record<string, unknown> | null | undefined
): void {
  if (!hasLocalStorage()) return;
  for (const key of REPORT_LOCAL_STORAGE_KEYS) {
    const raw = payload && key in payload ? payload[key] : null;
    if (typeof raw === "string") {
      try {
        globalThis.localStorage.setItem(key, raw);
      } catch {
        // ignore storage write failures
      }
      continue;
    }
    try {
      globalThis.localStorage.removeItem(key);
    } catch {
      // ignore storage write failures
    }
  }
}

export function applyCopylotLocalStorageState(
  payload: Record<string, unknown> | null | undefined
): void {
  if (!hasLocalStorage()) return;
  const entries = payload && typeof payload === "object" ? payload : {};
  const nextKeys = new Set(
    Object.keys(entries).filter((key) =>
      COPYLOT_LOCAL_STORAGE_PREFIXES.some((prefix) => key.startsWith(prefix))
    )
  );

  try {
    const existingToRemove: string[] = [];
    for (let index = 0; index < globalThis.localStorage.length; index += 1) {
      const key = globalThis.localStorage.key(index);
      if (!key) continue;
      if (!COPYLOT_LOCAL_STORAGE_PREFIXES.some((prefix) => key.startsWith(prefix))) continue;
      if (!nextKeys.has(key)) existingToRemove.push(key);
    }
    for (const key of existingToRemove) {
      try {
        globalThis.localStorage.removeItem(key);
      } catch {
        // ignore storage failures
      }
    }
  } catch {
    // ignore enumeration failures
  }

  for (const [key, raw] of Object.entries(entries)) {
    if (!COPYLOT_LOCAL_STORAGE_PREFIXES.some((prefix) => key.startsWith(prefix))) continue;
    if (typeof raw === "string") {
      try {
        globalThis.localStorage.setItem(key, raw);
      } catch {
        // ignore storage write failures
      }
      continue;
    }
    try {
      globalThis.localStorage.removeItem(key);
    } catch {
      // ignore storage write failures
    }
  }
}
