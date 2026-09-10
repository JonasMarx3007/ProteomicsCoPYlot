import { useEffect, useState, type ReactNode } from "react";
import { initializeBrowserSession, shouldResetClientStateOnBrowserLoad } from "../lib/datasetAvailability";
import { clearCopylotClientStorageState } from "../lib/restoreUiState";
import { initializeAdvancedPlotState, initializeSessionTheme } from "../lib/appSettings";
import { onceAsync } from "../lib/onceAsync";

const initialize = onceAsync(async () => {
  const resetClient = shouldResetClientStateOnBrowserLoad();
  await initializeBrowserSession();
  if (resetClient) clearCopylotClientStorageState();
  initializeSessionTheme();
  initializeAdvancedPlotState();
});

export default function AnalysisSessionGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    initialize().then(() => { if (!cancelled) setReady(true); })
      .catch(() => { if (!cancelled) setError("Could not initialize a new analysis. Your previous state has not been opened. Check the backend connection and reload to retry."); });
    return () => { cancelled = true; };
  }, []);
  if (error) return <div role="alert" className="p-6 text-red-700">{error}</div>;
  if (!ready) return <div role="status" className="p-6">Initializing analysis…</div>;
  return children;
}
