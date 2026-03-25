import { useCallback, useEffect, useMemo, useState } from "react";
import { getCurrentDatasets } from "./api";
import type { AnnotationKind, CurrentDatasetsResponse } from "./types";
import { IS_VIEWER_MODE } from "./appMode";

export type AnnotationKindOption = {
  value: AnnotationKind;
  label: string;
};

export function availableAnnotationKinds(
  datasets: CurrentDatasetsResponse | null
): AnnotationKind[] {
  const kinds: AnnotationKind[] = [];
  if (datasets?.protein) kinds.push("protein");
  if (datasets?.phospho) kinds.push("phospho");
  if (datasets?.phosprot) kinds.push("phosprot");
  return kinds;
}

export function annotationKindOptions(
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

export function useCurrentDatasetsSnapshot() {
  const [datasets, setDatasets] = useState<CurrentDatasetsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (silent = false) => {
    try {
      if (!silent) {
        setLoading(true);
      }
      setError(null);
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
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (datasets !== null) return;
    const timer = window.setTimeout(() => {
      refresh(true).catch(() => {
        // next retry is scheduled by this effect if datasets stays null
      });
    }, IS_VIEWER_MODE ? 500 : 2000);
    return () => window.clearTimeout(timer);
  }, [datasets, refresh]);

  const kinds = useMemo(() => availableAnnotationKinds(datasets), [datasets]);
  const options = useMemo(() => annotationKindOptions(kinds), [kinds]);

  return {
    datasets,
    loading,
    error,
    refresh,
    availableKinds: kinds,
    kindOptions: options,
  };
}
