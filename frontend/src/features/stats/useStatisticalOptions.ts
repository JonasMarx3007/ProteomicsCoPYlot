import { useEffect, useEffectEvent } from "react";

import { getStatisticalOptions, isAbortError } from "../../lib/api";
import type { AnnotationKind, StatisticalOptionsResponse, StatsIdentifier } from "../../lib/types";

/** A state updater that keeps the current condition while it still exists. */
export function keepCondition(available: string[], fallback = available[0] ?? "") {
  return (current: string) => (available.includes(current) ? current : fallback);
}

/** A state updater that keeps the current identifier while it still exists. */
export function keepIdentifier(data: StatisticalOptionsResponse) {
  return (current: StatsIdentifier) =>
    data.availableIdentifiers.some((item) => item.key === current)
      ? current
      : data.availableIdentifiers[0]?.key ?? "workflow";
}

/**
 * Loads the statistics options for the annotation kind and hands every answer to
 * the panel (`onLoaded`), which stores it and reconciles its selections.
 */
export function useStatisticalOptionsLoader(
  kind: AnnotationKind,
  enabled: boolean,
  onLoaded: (data: StatisticalOptionsResponse) => void,
  onError: (message: string) => void,
) {
  const loaded = useEffectEvent(onLoaded);
  const failed = useEffectEvent(onError);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    getStatisticalOptions(kind, { signal: controller.signal })
      .then((data) => loaded(data))
      .catch((err) => {
        if (!isAbortError(err)) {
          failed(err instanceof Error ? err.message : "Failed to load statistical options");
        }
      });
    return () => controller.abort();
  }, [kind, enabled]);
}
