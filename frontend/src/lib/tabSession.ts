import { clearCopylotClientStorageState } from "./restoreUiState";

const STORAGE_KEY = "copylot.tab.id";

function tabId(): string {
  const fresh = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, "0")).join("");
  try {
    const navigation = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    const previous = sessionStorage.getItem(STORAGE_KEY);
    const reuse = navigation?.type === "reload" && previous && /^[a-f0-9]{32}$/.test(previous);
    const id = reuse ? previous : fresh();
    if (!reuse) {
      clearCopylotClientStorageState();
      sessionStorage.removeItem("pcopylot.skipBrowserSessionResetOnce.v1");
    }
    sessionStorage.setItem(STORAGE_KEY, id);
    return id;
  } catch {
    return fresh();
  }
}

export const TAB_API_PREFIX = `/api/tabs/${tabId()}`;
export const TAB_API_BASE = `${(import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "")}${TAB_API_PREFIX}`;
