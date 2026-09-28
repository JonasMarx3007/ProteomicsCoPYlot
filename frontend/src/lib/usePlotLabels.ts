import { useEffect, useState } from "react";
import { getQcPlotOptions } from "./api";
import { subscribeDatasetStateChanged } from "./datasetEvents";
import type { AnnotationKind, ContextMode, QcPlotOptionsResponse } from "./types";

export function usePlotLabels(workflow: string, mode: ContextMode | null, enabled: boolean) {
  let kind = ({ protein: "protein", phosphosite: "phospho", phosphoprotein: "phosprot" } as Record<string, string>)[workflow] || "";
  const selected = mode?.kind;
  if (selected === "protein" || selected === "phospho" || selected === "phosprot") kind = selected;
  const [result, setResult] = useState<{ kind: string; data: QcPlotOptionsResponse } | null>(null);
  useEffect(() => {
    if (!enabled || !kind) return;
    let controller: AbortController | null = null;
    const refresh = () => {
      controller?.abort();
      controller = new AbortController();
      const signal = controller.signal;
      setResult(null);
      void getQcPlotOptions(kind as AnnotationKind, { signal }).then(data => {
        if (!signal.aborted) setResult({ kind, data });
      }).catch(() => { /* Unavailable metadata must not leave stale labels. */ });
    };
    refresh();
    const unsubscribe = subscribeDatasetStateChanged(refresh);
    return () => { controller?.abort(); unsubscribe(); };
  }, [kind, enabled]);
  return enabled && result?.kind === kind ? result.data : null;
}
