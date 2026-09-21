import SummaryCard from "../../components/SummaryCard";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getCurrentAnnotation, getCurrentDatasets } from "../../lib/api";
import type {
  AnnotationFilterConfig,
  AnnotationImputationInfo,
  AnnotationKind,
  AnnotationResultResponse,
  CurrentDatasetsResponse,
} from "../../lib/types";
import { NORMALIZATION_LABELS } from "../../lib/types";
import CurrentDatasetsPanel from "../upload/CurrentDatasetsPanel";
import { IS_VIEWER_MODE } from "../../lib/appMode";

const annotationKinds: AnnotationKind[] = ["protein", "phospho", "phosprot"];

const labels: Record<AnnotationKind, string> = {
  protein: "Protein",
  phospho: "Phospho",
  phosprot: "Phosphoprotein",
};

const emptyAnnotations: Record<AnnotationKind, AnnotationResultResponse | null> = {
  protein: null,
  phospho: null,
  phosprot: null,
};

export default function AnnotationViewerPage() {
  const [datasets, setDatasets] = useState<CurrentDatasetsResponse | null>(null);
  const [annotations, setAnnotations] = useState<
    Record<AnnotationKind, AnnotationResultResponse | null>
  >(emptyAnnotations);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [viewerRefreshAttempts, setViewerRefreshAttempts] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const currentDatasets = await getCurrentDatasets();
      const annotationEntries = await Promise.all(
        annotationKinds.map(async (kind) => {
          try {
            const annotation = await getCurrentAnnotation(kind);
            return [kind, annotation] as const;
          } catch {
            return [kind, null] as const;
          }
        })
      );

      setDatasets(currentDatasets);
      setAnnotations(
        annotationEntries.reduce(
          (acc, [kind, annotation]) => ({ ...acc, [kind]: annotation }),
          emptyAnnotations
        )
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    load().catch((err) => {
      if (cancelled) return;
      setError(err instanceof Error ? err.message : "Failed to load annotation status");
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [load]);

  const availableStatuses = useMemo(
    () =>
      annotationKinds.filter((kind) => {
        const annotation = annotations[kind];
        return annotation !== null;
      }),
    [annotations]
  );

  useEffect(() => {
    if (!IS_VIEWER_MODE || loading) return;
    const hasDatasets =
      Boolean(datasets?.protein) ||
      Boolean(datasets?.phospho) ||
      Boolean(datasets?.phosprot) ||
      Boolean(datasets?.peptide);
    if (hasDatasets && availableStatuses.length > 0) return;
    if (viewerRefreshAttempts >= 20) return;
    const timer = window.setTimeout(() => {
      setViewerRefreshAttempts((value) => value + 1);
      load().catch(() => {
        // keep current state if backend is still completing startup
      });
    }, 700);
    return () => window.clearTimeout(timer);
  }, [availableStatuses.length, datasets, loading, load, viewerRefreshAttempts]);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
        Viewer mode is read-only. Annotation settings and filtering are loaded from{" "}
        <code>viewer_config.json</code>.
      </section>

      <CurrentDatasetsPanel current={datasets} />

      {error ? (
        <section className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </section>
      ) : null}

      {loading ? (
        <section className="rounded-2xl border border-slate-200 bg-white px-4 py-6 text-sm text-slate-600">
          Loading annotation status...
        </section>
      ) : null}

      {!loading && availableStatuses.length === 0 ? (
        <section className="rounded-2xl border border-dashed border-slate-300 bg-white px-4 py-6 text-sm text-slate-500">
          No annotation status is currently available.
        </section>
      ) : null}

      {availableStatuses.map((kind) => {
        const annotation = annotations[kind];
        if (!annotation) return null;

        return (
          <section key={kind} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">{labels[kind]} Annotation</h3>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <SummaryCard
                label="Log2 transformed"
                value={annotation.isLog2Transformed ? "Yes" : "No"}
              />
              <SummaryCard label="Metadata source" value={annotation.metadataSource} />
              <SummaryCard label="Conditions" value={String(annotation.conditionCount)} />
              <SummaryCard label="Samples" value={String(annotation.sampleCount)} />
              <SummaryCard label="Filtered rows" value={String(annotation.filteredRows)} />
              <SummaryCard label="Filter" value={formatFilterSummary(annotation.filter)} />
              {annotation.filter && annotation.filter.normalization !== "none" ? (
                // Only when there is something to report. "Normalization: None"
                // is a card that says nothing, and the absence of the card is
                // the same statement with less to read.
                <SummaryCard
                  label="Normalization"
                  value={NORMALIZATION_LABELS[annotation.filter.normalization]}
                />
              ) : null}
              <SummaryCard
                label="Imputation"
                value={formatImputationSummary(annotation.imputation)}
              />
            </div>
          </section>
        );
      })}
    </div>
  );
}


// The rule the filter actually applied, rather than two of its parameters.
// "per_group / min 3" does not say whether 3 was needed in every group or in
// one, and said nothing at all about a percentage filter.
function formatFilterSummary(filter: AnnotationFilterConfig | null): string {
  if (!filter) return "n/a";
  const scope = filter.mode === "in_at_least_one_group" ? "in at least one group" : "in every group";
  const threshold =
    filter.method === "percentage"
      ? `${formatValue(filter.minPercentage)}% valid values`
      : `min ${filter.minPresent} valid values`;
  return `${threshold} ${scope}`;
}

function formatImputationSummary(imputation: AnnotationImputationInfo | null): string {
  if (!imputation) return "none";
  const mode = imputation.mode ?? "none";
  if (!mode || mode === "none") return "none";
  const parameters =
    mode === "numerical"
      ? `downshift=${formatValue(imputation.downShift)}, width=${formatValue(imputation.width)}`
      : `q=${formatValue(imputation.qValue)}, adj_std=${formatValue(imputation.adjustStd)}`;
  // A configured imputation that was refused keeps its mode so the refusal can
  // be reported; saying only the parameters would claim values were imputed.
  const applied = imputation.applied ? "" : " - NOT applied, see warnings";
  return `${mode}, ${parameters}${applied}`;
}

function formatValue(value: number | null): string {
  if (value == null) return "n/a";
  return String(value);
}
