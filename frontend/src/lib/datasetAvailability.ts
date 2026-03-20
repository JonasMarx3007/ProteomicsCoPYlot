import { useCallback, useEffect, useMemo, useState } from "react";
import { getCurrentDatasets } from "./api";
import type { AnnotationKind, CurrentDatasetsResponse } from "./types";

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
  return kinds;
}

export function annotationKindOptions(
  kinds: AnnotationKind[]
): AnnotationKindOption[] {
  return kinds.map((kind) => ({
    value: kind,
    label: kind === "protein" ? "Protein" : "Phospho",
  }));
}

export function useCurrentDatasetsSnapshot() {
  const [datasets, setDatasets] = useState<CurrentDatasetsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const current = await getCurrentDatasets();
      setDatasets(current);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load current datasets");
      setDatasets(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

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
