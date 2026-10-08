import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getCurrentDatasets,
  resetBrowserSessionState,
  setActiveDatasetPackage,
  setActiveMetadataProfile,
} from "./api";
import type { AnnotationKind, CurrentDatasetsResponse } from "./types";
import { IS_VIEWER_MODE } from "./appMode";
import { subscribeDatasetStateChanged } from "./datasetEvents";
import { onceAsync } from "./onceAsync";

// Ensure browser-session reset happens once per page load, even if multiple
// pipeline pages mount/unmount this hook.
const SKIP_BROWSER_SESSION_RESET_ONCE_KEY = "pcopylot.skipBrowserSessionResetOnce.v1";
const VIEWER_BOOTSTRAP_MAX_RETRIES = 240; // ~120s at 500ms intervals.
const BROWSER_SESSION_RESET_ENABLED = (() => {
  const explicit = String(import.meta.env.VITE_RESET_ON_BROWSER_LOAD ?? "").trim().toLowerCase();
  if (explicit) {
    return explicit === "1" || explicit === "true" || explicit === "yes" || explicit === "on";
  }
  // Default behavior:
  // - app mode: reset state on full browser refresh
  // - viewer mode: keep loaded viewer project state intact
  return !IS_VIEWER_MODE;
})();

function consumeSkipBrowserSessionResetOnceFlag(): boolean {
  try {
    const raw = String(globalThis.sessionStorage?.getItem(SKIP_BROWSER_SESSION_RESET_ONCE_KEY) ?? "")
      .trim()
      .toLowerCase();
    if (raw === "1" || raw === "true" || raw === "yes" || raw === "on") {
      globalThis.sessionStorage?.removeItem(SKIP_BROWSER_SESSION_RESET_ONCE_KEY);
      return true;
    }
  } catch {
    // Ignore sessionStorage access failures.
  }
  return false;
}

function hasSkipBrowserSessionResetOnceFlag(): boolean {
  try {
    const raw = String(globalThis.sessionStorage?.getItem(SKIP_BROWSER_SESSION_RESET_ONCE_KEY) ?? "")
      .trim()
      .toLowerCase();
    return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
  } catch {
    return false;
  }
}

export function shouldResetClientStateOnBrowserLoad(): boolean {
  return BROWSER_SESSION_RESET_ENABLED && !hasSkipBrowserSessionResetOnceFlag();
}

export const initializeBrowserSession = onceAsync(async () => {
  const skip = consumeSkipBrowserSessionResetOnceFlag();
  if (BROWSER_SESSION_RESET_ENABLED && !skip) await resetBrowserSessionState();
});

export type AnnotationKindOption = {
  value: AnnotationKind;
  label: string;
};

function availableAnnotationKinds(
  datasets: CurrentDatasetsResponse | null
): AnnotationKind[] {
  const kinds: AnnotationKind[] = [];
  if (datasets?.protein) kinds.push("protein");
  if (datasets?.phospho) kinds.push("phospho");
  if (datasets?.phosprot) kinds.push("phosprot");
  return kinds;
}

function annotationKindOptions(
  kinds: AnnotationKind[]
): AnnotationKindOption[] {
  return kinds.map((kind) => ({
    value: kind,
    label:
      kind === "protein"
        ? "Protein"
        : kind === "phospho"
          ? "Phospho"
          : "Phosphoprotein",
  }));
}

export function useDatasetRevision() {
  const [revision, setRevision] = useState(0);
  useEffect(() => subscribeDatasetStateChanged(() => setRevision(value => value + 1)), []);
  return revision;
}

export function useCurrentDatasetsSnapshot() {
  const [datasets, setDatasets] = useState<CurrentDatasetsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const viewerRetryCountRef = useRef(0);

  const refresh = useCallback(async (silent = false) => {
    try {
      if (!silent) {
        setLoading(true);
      }
      setError(null);
      await initializeBrowserSession();
      const current = await getCurrentDatasets();
      setDatasets(current);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load current datasets");
      setDatasets(null);
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function initialize() {
      if (cancelled) return;
      await refresh();
    }

    initialize().catch(() => {
      // refresh() already handles state updates on failure
    });
    return () => {
      cancelled = true;
    };
  }, [refresh]);

  useEffect(() => {
    return subscribeDatasetStateChanged((snapshot) => {
      if (snapshot) {
        setDatasets(snapshot);
        setError(null);
        return;
      }
      refresh(true).catch(() => {
        // keep previous snapshot if refresh fails transiently
      });
    });
  }, [refresh]);

  useEffect(() => {
    const hasAnyDataset =
      Boolean(datasets?.protein) ||
      Boolean(datasets?.phospho) ||
      Boolean(datasets?.phosprot) ||
      Boolean(datasets?.peptide);

    if (!IS_VIEWER_MODE) {
      if (datasets !== null) return;
      const timer = window.setTimeout(() => {
        refresh(true).catch(() => {
          // next retry is scheduled by this effect if datasets stays null
        });
      }, 2000);
      return () => window.clearTimeout(timer);
    }

    if (hasAnyDataset) return;
    if (viewerRetryCountRef.current >= VIEWER_BOOTSTRAP_MAX_RETRIES) return;

    const timer = window.setTimeout(() => {
      viewerRetryCountRef.current += 1;
      refresh(true).catch(() => {
        // continue retrying for a short bootstrap window in viewer mode
      });
    }, 500);
    return () => window.clearTimeout(timer);
  }, [datasets, refresh]);

  const kinds = useMemo(() => availableAnnotationKinds(datasets), [datasets]);
  const options = useMemo(() => annotationKindOptions(kinds), [kinds]);
  const availablePackages = useMemo(
    () => (datasets?.availablePackages ?? []).filter((value) => value.trim().length > 0),
    [datasets]
  );
  const activePackage = datasets?.activePackage ?? availablePackages[0] ?? "Data";
  const availableMetadataProfiles = useMemo(
    () => (datasets?.availableMetadataProfiles ?? []).filter((value) => value.trim().length > 0),
    [datasets]
  );
  const autoGeneratedMetadataProfiles = useMemo(
    () => (datasets?.autoGeneratedMetadataProfiles ?? []).filter((value) => value.trim().length > 0),
    [datasets]
  );
  const activeMetadataProfile =
    datasets?.activeMetadataProfile ?? availableMetadataProfiles[0] ?? "Metadata";

  const setActivePackage = useCallback(async (packageName: string) => {
    const next = packageName.trim();
    if (!next) return;
    const updated = await setActiveDatasetPackage(next);
    setDatasets(updated);
  }, []);
  const setMetadataProfile = useCallback(async (profileName: string) => {
    const next = profileName.trim();
    if (!next) return;
    const updated = await setActiveMetadataProfile(next);
    setDatasets(updated);
  }, []);

  return {
    datasets,
    loading,
    error,
    refresh,
    activePackage,
    availablePackages,
    setActivePackage,
    activeMetadataProfile,
    availableMetadataProfiles,
    autoGeneratedMetadataProfiles,
    setMetadataProfile,
    availableKinds: kinds,
    kindOptions: options,
  };
}
