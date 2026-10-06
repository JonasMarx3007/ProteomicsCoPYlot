import { useEffect, useState } from "react";
import type { RenderedNotebook } from "../../components/NotebookDownload";
import { getAnovaNotebookTables, isAbortError } from "../../lib/api";
import { fetchPlot } from "../../lib/fetchPlot";
import type { AnovaResultResponse } from "../../lib/types";
import { ImageSection, InfoSection, Notice, TableSection } from "./statsShared";
import { sanitizeFilenamePart } from "./statsHelpers";

export default function AnovaOutput({ result, plotUrl, selectedCluster }: {
  result: AnovaResultResponse; plotUrl: string; selectedCluster?: string;
}) {
  const [rendered, setRendered] = useState<RenderedNotebook | null>(null);
  const [captured, setCaptured] = useState<{ token: string; data: AnovaResultResponse } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const noHeatmap = result.significantCount === 0;

  // A table with no significant hits still has a reproducible analysis. Capture
  // it without adding an empty heatmap to the interface.
  useEffect(() => {
    if (!noHeatmap) return;
    const controller = new AbortController();
    fetchPlot(plotUrl, controller.signal).then(async response => {
      if (!response.ok) throw new Error("Could not prepare the ANOVA notebook.");
      await response.arrayBuffer();
      const token = response.headers.get("X-CoPYlot-Notebook");
      if (!controller.signal.aborted) setRendered({ url: plotUrl, token: token && /^[A-Za-z0-9_-]{32}$/.test(token) ? token : null });
    }).catch(cause => {
      if (!controller.signal.aborted && !isAbortError(cause)) setError(String(cause.message ?? cause));
    });
    return () => controller.abort();
  }, [noHeatmap, plotUrl]);

  useEffect(() => {
    if (rendered?.url !== plotUrl || !rendered.token) return;
    const controller = new AbortController();
    const token = rendered.token;
    getAnovaNotebookTables(result.kind, token, controller.signal).then(data => {
      if (!controller.signal.aborted) setCaptured({ token, data });
    }).catch(cause => {
      if (!controller.signal.aborted && !isAbortError(cause)) setError(String(cause.message ?? cause));
    });
    return () => controller.abort();
  }, [result.kind, plotUrl, rendered]);

  const snapshot = rendered?.url === plotUrl && captured?.token === rendered?.token ? captured : null;
  const data = snapshot?.data ?? result;
  const notebook = snapshot ? rendered : null;
  const prefix = `anova_${data.source}_${data.kind}`;
  const rows = selectedCluster === undefined ? data.rows
    : data.clusterRows.filter(row => String(row.cluster) === selectedCluster);
  const title = selectedCluster !== undefined ? `Cluster ${selectedCluster}`
    : data.source === "anova_cluster" ? "ANOVA Cluster" : "ANOVA";
  return <>
    <Notice error={error} />
    {noHeatmap ? <InfoSection message="No rows passed the selected ANOVA threshold, so no significant-row heatmap or clusters were generated." />
      : <ImageSection title={`${title} Heatmap`} url={plotUrl} notebook={rendered}
          onRendered={(url, token) => setRendered({ url, token })} />}
    <TableSection title={selectedCluster === undefined ? "Result Table" : `${title} Result Table`}
      rows={rows} filename={`${prefix}${selectedCluster === undefined ? "" : `_cluster_${selectedCluster}`}.csv`}
      plotUrl={plotUrl} notebook={notebook} />
    {selectedCluster === undefined && data.postHocRows.length > 0 ? <TableSection
      title={`Post-hoc: ${data.postHocMethod ?? "Tukey HSD"}${data.postHocComparison ? ` — ${data.postHocComparison}` : ""} (${data.postHocSignificantCount} significant of ${data.postHocRows.length} comparisons, ANOVA-significant rows only)`}
      rows={data.postHocRows} plotUrl={plotUrl} notebook={notebook}
      filename={`${prefix}_tukey${data.postHocComparison ? `_${sanitizeFilenamePart(data.postHocComparison.replace(/\s+vs\s+/, "_vs_"))}` : ""}.csv`} /> : null}
  </>;
}
