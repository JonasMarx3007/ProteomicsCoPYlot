import { AssistantInput, AssistantSelect } from "../../components/AssistantFields";
import SelectField from "../../components/SelectField";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, getDistributionSummary, isAbortError } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import {
  PLOT_DOWNLOAD_FORMAT_OPTIONS,
  type PlotDownloadFormat,
  withPlotDownloadFilename,
  withPlotDownloadFormat,
} from "../../lib/plotDownload";
import { withBasePath } from "../../lib/basePath";
import { useAdvancedPlotSignal } from "../../lib/useAdvancedPlotSignal";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import type { AnnotationKind, DistributionSummaryResponse } from "../../lib/types";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function DistributionPage({ advancedPlotOptions, onContextModeChange }: Props) {
  const advancedPlotSignal = useAdvancedPlotSignal();
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("data.distribution.v1", {}),
    []
  );
  const [kind, setKind] = useState<AnnotationKind>(() => {
    const value = String(persisted.kind ?? "protein");
    return value === "phospho" || value === "phosprot" ? value : "protein";
  });
  const { availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<DistributionSummaryResponse | null>(null);
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>(() => {
    const value = String(persisted.downloadFormat ?? "png");
    return value === "jpg" || value === "webp" || value === "pdf" ? value : "png";
  });
  const [randomSeed, setRandomSeed] = useState(() => Number(persisted.randomSeed ?? 187));
  useEffect(() => {
    onContextModeChange?.(JSON.stringify({ kind, randomSeed }));
  }, [onContextModeChange, kind, randomSeed]);

  useEffect(() => {
    writePersistedUiState("data.distribution.v1", { kind, downloadFormat, randomSeed });
  }, [kind, downloadFormat, randomSeed]);

  const loadSummary = useCallback(async (signal?: AbortSignal) => {
    if (!availableKinds.includes(kind)) {
      setSummary(null);
      setError("Please upload a protein, phospho, or phosphoprotein dataset first.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const data = await getDistributionSummary(kind, { signal });
      setSummary(data);
    } catch (err) {
      if (isAbortError(err)) return;
      setError(err instanceof Error ? err.message : "Failed to load distribution summary");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [availableKinds, kind]);

  useEffect(() => {
    if (availableKinds.length === 0) {
      setSummary(null);
      return;
    }
    if (!availableKinds.includes(kind)) {
      setKind(availableKinds[0]);
      return;
    }
    const controller = new AbortController();
    loadSummary(controller.signal);
    return () => controller.abort();
  }, [kind, availableKinds, loadSummary]);

  const qqPlotUrl = useMemo(
    () => {
      void advancedPlotSignal;
      return buildPlotUrl(`/api/plots/distribution/${kind}/qqnorm.png`, { randomSeed });
    },
    [kind, randomSeed, advancedPlotSignal]
  );
  const qqPlotDownloadUrl = withPlotDownloadFormat(qqPlotUrl, downloadFormat);
  const qqPlotDownloadFilename = withPlotDownloadFilename(`qqnorm_${kind}.png`, downloadFormat);
  const qqReferenceImageUrl = withBasePath("/assets/qqnorm.jpg");
  const qqReferenceTextUrl = withBasePath("/assets/qqnorm_txt.jpg");

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Distribution</h2>

        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <SelectField
            label="Dataset level"
            value={kindOptions.length === 0 ? "" : kind}
            onChange={(value) => setKind(value as AnnotationKind)}
            options={kindOptions}
          />
          <label className="grid gap-1 text-sm text-slate-700">
            <span>Random seed</span>
            <AssistantInput
              type="number"
              min={0}
              step={1}
              value={randomSeed}
              onChange={(event) =>
                setRandomSeed(Math.max(0, Math.round(Number(event.target.value) || 0)))
              }
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
            />
          </label>
          <div className="self-end">
            <button
              type="button"
              onClick={() => void loadSummary()}
              disabled={loading}
              className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "Refreshing..." : "Refresh"}
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
      </section>

      {kindOptions.length > 0 ? advancedPlotOptions : null}

      {kindOptions.length === 0 ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
          Upload a protein, phospho, or phosphoprotein dataset in the Data tab to enable distribution plots.
        </section>
      ) : null}

      {kindOptions.length > 0 && summary ? (
        <>
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-slate-900">QQ Norm Plot</h3>
              <div className="flex flex-wrap items-center gap-2">
                <AssistantSelect
                  value={downloadFormat}
                  onChange={(e) => setDownloadFormat(e.target.value as PlotDownloadFormat)}
                  className="rounded-xl border border-slate-300 bg-white px-2 py-2 text-sm text-slate-700 outline-none focus:border-slate-900"
                >
                  {PLOT_DOWNLOAD_FORMAT_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </AssistantSelect>
                <a
                  href={qqPlotDownloadUrl}
                  download={qqPlotDownloadFilename}
                  className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                >
                  Download Plot
                </a>
              </div>
            </div>
            {summary.warnings.length > 0 ? (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {summary.warnings.join(" ")}
              </div>
            ) : null}
            <div className="mt-4">
              <img src={qqPlotUrl} alt="QQ norm plot" className="w-full rounded-xl border border-slate-200" />
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">QQ Norm Reference</h3>
            <div className="mt-4 grid gap-4 grid-cols-1">
              <img
                src={qqReferenceImageUrl}
                alt="QQ norm reference"
                className="w-full rounded-xl border border-slate-200"
              />
              <img
                src={qqReferenceTextUrl}
                alt="QQ norm reference text"
                className="w-full rounded-xl border border-slate-200"
              />
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
