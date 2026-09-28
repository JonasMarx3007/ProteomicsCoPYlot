import { SizeRow } from "../../components/PlotFields";
import { withoutStaticSize } from "../../lib/plotRenderType";
import { restorePlotDimensionCm, restorePlotDpi } from "../../lib/plotLimits";
import { AssistantSelect } from "../../components/AssistantFields";
import { collectColumns } from "../../lib/tableData";
import { rowsToCsv } from "../../lib/tableData";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, getComparisonOptions, getComparisonTable, isAbortError } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import {
  PLOT_DOWNLOAD_FORMAT_OPTIONS,
  coercePlotDownloadFormat,
  type PlotDownloadFormat,
  withPlotDownloadFilename,
  withPlotDownloadFormat,
} from "../../lib/plotDownload";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import { useAdvancedPlotSignal } from "../../lib/useAdvancedPlotSignal";
import type {
  AnnotationKind,
  ComparisonOptionsResponse,
  ComparisonTab,
} from "../../lib/types";
import PreviewTable from "../../components/PreviewTable";
import SelectField from "../../components/SelectField";
import TextField from "../../components/TextField";
import type { ContextMode } from "../../lib/types";

type Props = {
  activeTab: ComparisonTab;
  onContextModeChange?: (mode: ContextMode | null) => void;
  advancedPlotOptions?: ReactNode;
};

type PlotView = {
  title: string;
  url: string;
  filename?: string;
  renderMode: "image" | "html";
} | null;

type TableRequest = {
  tab: ComparisonTab;
  params: Record<string, string | number | boolean>;
} | null;

export default function ComparisonPipelinePage({ activeTab, onContextModeChange, advancedPlotOptions }: Props) {
  const advancedPlotSignal = useAdvancedPlotSignal();
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("comparison.pipeline.v1", {}),
    []
  );
  const persistedPearson = (persisted.pearson as Record<string, unknown>) ?? {};
  const persistedVenn = (persisted.venn as Record<string, unknown>) ?? {};
  const { availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [kind, setKind] = useState<AnnotationKind>(() => {
    const value = String(persisted.kind ?? "protein").trim();
    return value === "protein" || value === "phospho" || value === "phosprot"
      ? value
      : "protein";
  });
  const [options, setOptions] = useState<ComparisonOptionsResponse | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [tableRows, setTableRows] = useState<Record<string, unknown>[]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>(() =>
    coercePlotDownloadFormat(persisted.downloadFormat)
  );

  const [pearson, setPearson] = useState({
    type: String(persistedPearson.type ?? "Normal"),
    mode: String(persistedPearson.mode ?? "Single"),
    sample1: String(persistedPearson.sample1 ?? ""),
    sample2: String(persistedPearson.sample2 ?? ""),
    condition1: String(persistedPearson.condition1 ?? ""),
    condition2: String(persistedPearson.condition2 ?? ""),
    alias1: String(persistedPearson.alias1 ?? ""),
    alias2: String(persistedPearson.alias2 ?? ""),
    color: String(persistedPearson.color ?? "#1f77b4"),
    header: true,
    widthCm: restorePlotDimensionCm(persistedPearson.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedPearson.heightCm, 12),
    dpi: restorePlotDpi(persistedPearson.dpi, 300),
  });

  const [venn, setVenn] = useState({
    mode: String(persistedVenn.mode ?? "Single"),
    first: String(persistedVenn.first ?? ""),
    second: String(persistedVenn.second ?? ""),
    third: String(persistedVenn.third ?? ""),
    alias1: String(persistedVenn.alias1 ?? ""),
    alias2: String(persistedVenn.alias2 ?? ""),
    alias3: String(persistedVenn.alias3 ?? ""),
    color1: String(persistedVenn.color1 ?? "#1f77b4"),
    color2: String(persistedVenn.color2 ?? "#ff7f0e"),
    color3: String(persistedVenn.color3 ?? "#2ca02c"),
    header: true,
    widthCm: restorePlotDimensionCm(persistedVenn.widthCm, 15),
    heightCm: restorePlotDimensionCm(persistedVenn.heightCm, 12),
    dpi: restorePlotDpi(persistedVenn.dpi, 300),
  });
  const [pearsonInteractiveSessionNonce] = useState(() => Date.now());

  useEffect(() => {
    writePersistedUiState("comparison.pipeline.v1", {
      kind,
      downloadFormat,
      pearson,
      venn,
    });
  }, [kind, downloadFormat, pearson, venn]);

  const hasKind = availableKinds.includes(kind);

  useEffect(() => {
    if (availableKinds.length === 0) {
      setOptions(null);
      return;
    }
    if (!availableKinds.includes(kind)) {
      setKind(availableKinds[0]);
    }
  }, [availableKinds, kind]);

  useEffect(() => {
    if (!hasKind) {
      setOptions(null);
      setOptionsLoading(false);
      setOptionsError(null);
      return;
    }

    const controller = new AbortController();
    setOptions(null);
    setOptionsLoading(true);
    setOptionsError(null);
    getComparisonOptions(kind, { signal: controller.signal })
      .then((payload) => {
        setOptions(payload);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setOptions(null);
        setOptionsError(err instanceof Error ? err.message : "Failed to load comparison options");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setOptionsLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [hasKind, kind]);

  useEffect(() => {
    if (!options) return;
    const samples = options.samples ?? [];
    const conditions = options.conditions ?? [];

    setPearson((prev) => {
      const sample1 = samples.includes(prev.sample1) ? prev.sample1 : samples[0] ?? "";
      const sample2 =
        samples.includes(prev.sample2) && prev.sample2 !== sample1
          ? prev.sample2
          : samples.find((value) => value !== sample1) ?? "";
      const condition1 = conditions.includes(prev.condition1) ? prev.condition1 : conditions[0] ?? "";
      const condition2 =
        conditions.includes(prev.condition2) && prev.condition2 !== condition1
          ? prev.condition2
          : conditions.find((value) => value !== condition1) ?? "";
      return { ...prev, sample1, sample2, condition1, condition2 };
    });
  }, [options]);

  useEffect(() => {
    if (!options) return;
    const pool = venn.mode === "Single" ? options.samples ?? [] : options.conditions ?? [];

    setVenn((prev) => {
      const first = pool.includes(prev.first) ? prev.first : pool[0] ?? "";
      const second =
        pool.includes(prev.second) && prev.second !== first
          ? prev.second
          : pool.find((value) => value !== first) ?? "";
      const third =
        prev.third && pool.includes(prev.third) && prev.third !== first && prev.third !== second
          ? prev.third
          : "";
      return { ...prev, first, second, third };
    });
  }, [options, venn.mode]);

  const pearsonReady = useMemo(() => {
    if (pearson.mode === "Single") {
      return Boolean(pearson.sample1 && pearson.sample2 && pearson.sample1 !== pearson.sample2);
    }
    return Boolean(
      pearson.condition1 && pearson.condition2 && pearson.condition1 !== pearson.condition2
    );
  }, [pearson]);

  const vennReady = useMemo(() => {
    if (!venn.first || !venn.second || venn.first === venn.second) return false;
    if (!venn.third) return true;
    return venn.third !== venn.first && venn.third !== venn.second;
  }, [venn]);

  const plotView = useMemo<PlotView>(() => {
    void advancedPlotSignal;
    if (!hasKind || !options) return null;

    if (activeTab === "pearson") {
      if (!pearsonReady) return null;
      const params: Record<string, string | number | boolean> = {
        type: pearson.type,
        mode: pearson.mode,
        sample1: pearson.sample1,
        sample2: pearson.sample2,
        condition1: pearson.condition1,
        condition2: pearson.condition2,
        alias1: pearson.alias1,
        alias2: pearson.alias2,
        color: pearson.color,
        header: pearson.header,
        widthCm: pearson.widthCm,
        heightCm: pearson.heightCm,
        dpi: pearson.dpi,
      };
      const pearsonInteractive = String(pearson.type || "").trim().toLowerCase() === "interactive";
      const pearsonPlotParams = pearsonInteractive
        ? { ...withoutStaticSize(params), _interactiveV: pearsonInteractiveSessionNonce }
        : params;
      return {
        title: "Pearson Correlation",
        filename: pearsonInteractive ? undefined : `comparison_pearson_${kind}.png`,
        renderMode: pearsonInteractive ? "html" : "image",
        url: buildPlotUrl(
          pearsonInteractive
            ? `/api/plots/comparison/${kind}/pearson.html`
            : `/api/plots/comparison/${kind}/pearson.png`,
          pearsonPlotParams
        ),
      };
    }

    if (!vennReady) return null;
    const params: Record<string, string | number | boolean> = {
      mode: venn.mode,
      first: venn.first,
      second: venn.second,
      third: venn.third,
      alias1: venn.alias1,
      alias2: venn.alias2,
      alias3: venn.alias3,
      color1: venn.color1,
      color2: venn.color2,
      color3: venn.color3,
      header: venn.header,
      widthCm: venn.widthCm,
      heightCm: venn.heightCm,
      dpi: venn.dpi,
    };
    return {
      title: "Venn Diagram",
      filename: `comparison_venn_${kind}.png`,
      renderMode: "image",
      url: buildPlotUrl(`/api/plots/comparison/${kind}/venn.png`, params),
    };
  }, [activeTab, hasKind, kind, options, pearson, pearsonReady, venn, vennReady, pearsonInteractiveSessionNonce, advancedPlotSignal]);
  const plotDownloadUrl = useMemo(() => {
    if (!plotView || plotView.renderMode !== "image") return "";
    return withPlotDownloadFormat(plotView.url, downloadFormat);
  }, [plotView, downloadFormat]);
  const plotDownloadFilename = useMemo(() => {
    if (!plotView || plotView.renderMode !== "image" || !plotView.filename) return "";
    return withPlotDownloadFilename(plotView.filename, downloadFormat);
  }, [plotView, downloadFormat]);

  const tableRequest = useMemo<TableRequest>(() => {
    if (!hasKind || !options) return null;
    if (activeTab === "pearson") {
      if (!pearsonReady) return null;
      const params: Record<string, string | number | boolean> = {
        mode: pearson.mode,
        sample1: pearson.sample1,
        sample2: pearson.sample2,
        condition1: pearson.condition1,
        condition2: pearson.condition2,
        alias1: pearson.alias1,
        alias2: pearson.alias2,
      };
      return {
        tab: "pearson",
        params,
      };
    }
    if (!vennReady) return null;
    const params: Record<string, string | number | boolean> = {
      mode: venn.mode,
      first: venn.first,
      second: venn.second,
      third: venn.third,
      alias1: venn.alias1,
      alias2: venn.alias2,
      alias3: venn.alias3,
    };
    return {
      tab: "venn",
      params,
    };
  }, [
    activeTab,
    hasKind,
    options,
    pearsonReady,
    pearson.mode,
    pearson.sample1,
    pearson.sample2,
    pearson.condition1,
    pearson.condition2,
    pearson.alias1,
    pearson.alias2,
    vennReady,
    venn.mode,
    venn.first,
    venn.second,
    venn.third,
    venn.alias1,
    venn.alias2,
    venn.alias3,
  ]);

  useEffect(() => {
    if (!onContextModeChange) return;
    if (!hasKind) {
      onContextModeChange(null);
      return;
    }
    const mode: ContextMode =
      activeTab === "pearson"
        ? {
            kind: kind,
            dataSource: "data",
            tab: "pearson",
            type: pearson.type,
            mode: pearson.mode,
            sample1: pearson.sample1,
            sample2: pearson.sample2,
            condition1: pearson.condition1,
            condition2: pearson.condition2,
            alias1: pearson.alias1,
            alias2: pearson.alias2,
          }
        : {
            kind: kind,
            dataSource: "data",
            tab: "venn",
            mode: venn.mode,
            first: venn.first,
            second: venn.second,
            third: venn.third,
            alias1: venn.alias1,
            alias2: venn.alias2,
            alias3: venn.alias3,
            color1: venn.color1,
            color2: venn.color2,
            color3: venn.color3,
          };
    onContextModeChange(mode);
  }, [
    onContextModeChange,
    activeTab,
    hasKind,
    kind,
    pearson.type,
    pearson.mode,
    pearson.sample1,
    pearson.sample2,
    pearson.condition1,
    pearson.condition2,
    pearson.alias1,
    pearson.alias2,
    venn.mode,
    venn.first,
    venn.second,
    venn.third,
    venn.alias1,
    venn.alias2,
    venn.alias3,
    venn.color1,
    venn.color2,
    venn.color3,
  ]);

  useEffect(() => {
    if (!tableRequest || !hasKind) {
      setTableRows([]);
      setTableLoading(false);
      setTableError(null);
      return;
    }

    const controller = new AbortController();
    setTableLoading(true);
    setTableError(null);
    getComparisonTable(kind, tableRequest.tab, tableRequest.params, { signal: controller.signal })
      .then((payload) => {
        setTableRows(payload.rows ?? []);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setTableRows([]);
        setTableError(err instanceof Error ? err.message : "Failed to load comparison table");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setTableLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [hasKind, kind, tableRequest]);

  const tableCsvUrl = useMemo(() => {
    if (tableRows.length === 0) return null;
    const columns = collectColumns(tableRows);
    if (columns.length === 0) return null;
    return `data:text/csv;charset=utf-8,${encodeURIComponent(rowsToCsv(tableRows, columns))}`;
  }, [tableRows]);

  async function handleImageError(url: string) {
    try {
      const response = await fetch(url);
      const text = await response.text();
      if (!response.ok) {
        try {
          const parsed = JSON.parse(text) as { detail?: string };
          if (parsed?.detail) {
            setImageError(parsed.detail);
            return;
          }
        } catch {}
      }
    } catch {}
    setImageError("Failed to load plot image. Check backend logs for details.");
  }

  const modePool = activeTab === "pearson"
    ? (pearson.mode === "Single" ? options?.samples ?? [] : options?.conditions ?? [])
    : (venn.mode === "Single" ? options?.samples ?? [] : options?.conditions ?? []);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Comparison Pipeline</h2>
        <div className="mt-4 grid max-w-2xl gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-2 block font-medium text-slate-700">Dataset level</span>
            <AssistantSelect
              value={kindOptions.length === 0 ? "" : kind}
              onChange={(event) => setKind(event.target.value as AnnotationKind)}
              disabled={kindOptions.length === 0}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
            >
              {kindOptions.length === 0 ? (
                <option value="">No dataset available</option>
              ) : (
                kindOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))
              )}
            </AssistantSelect>
          </label>
        </div>
      </section>

      {kindOptions.length === 0 ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
          Upload a protein, phospho, or phosphoprotein dataset in the Data tab to enable comparison plots.
        </section>
      ) : null}

      {kindOptions.length > 0 ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-slate-900">Options</h3>
          {optionsLoading ? (
            <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              Loading options...
            </div>
          ) : optionsError ? (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {optionsError}
            </div>
          ) : (
            <div className="mt-4">{renderOptions()}</div>
          )}
        </section>
      ) : null}

      {kindOptions.length > 0 ? advancedPlotOptions : null}

      {kindOptions.length > 0 ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">{activeTab === "pearson" ? "Pearson Correlation" : "Venn Diagram"}</h3>
            {plotView?.renderMode === "image" ? (
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
                  href={plotDownloadUrl}
                  download={plotDownloadFilename}
                  className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                >
                  Download Plot
                </a>
              </div>
            ) : plotView?.renderMode === "html" ? (
              <a
                href={plotView.url}
                target="_blank"
                rel="noreferrer"
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Open Interactive Plot
              </a>
            ) : null}
          </div>

          {plotView ? (
            <div className="mt-4">
              {plotView.renderMode === "image" ? (
                <img
                  key={plotView.url}
                  src={plotView.url}
                  alt={plotView.title}
                  className="w-full rounded-xl border border-slate-200"
                  onLoad={() => setImageError(null)}
                  onError={() => {
                    handleImageError(plotView.url);
                  }}
                />
              ) : (
                <iframe
                  sandbox="allow-scripts allow-downloads"
                  key={plotView.url}
                  src={plotView.url}
                  title={plotView.title}
                  className="block w-full rounded-xl border border-slate-200"
                  style={{ height: `max(${cmToIframeHeight(12)}px, 78vh)` }}
                  onLoad={() => setImageError(null)}
                />
              )}
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              {modePool.length === 0
                ? "No selectable samples/conditions are available for this dataset."
                : "Select valid entries to render the plot."}
            </div>
          )}

          {imageError ? (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {imageError}
            </div>
          ) : null}
        </section>
      ) : null}

      {kindOptions.length > 0 ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">Summary Table</h3>
            {tableCsvUrl ? (
              <a
                href={tableCsvUrl}
                download={`comparison_${activeTab}_${kind}.csv`}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download CSV
              </a>
            ) : null}
          </div>
          <div className="mt-4">
            {tableLoading ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                Loading table...
              </div>
            ) : tableError ? (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {tableError}
              </div>
            ) : (
              <PreviewTable rows={tableRows} emptyText="No table rows available for the current selection." />
            )}
          </div>
        </section>
      ) : null}
    </div>
  );

  function renderOptions() {
    const samples = options?.samples ?? [];
    const conditions = options?.conditions ?? [];

    if (activeTab === "pearson") {
      const pool = pearson.mode === "Single" ? samples : conditions;
      return (
        <div className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-2 max-w-2xl">
            <SelectField
              labels={{ "": "None" }}
              label="Mode"
              value={pearson.mode}
              options={["Single", "Condition"]}
              onChange={(value) => setPearson({ ...pearson, mode: value })}
            />
            <SelectField
              labels={{ "": "None" }}
              label="Type"
              value={pearson.type}
              options={["Normal", "Interactive"]}
              onChange={(value) => setPearson({ ...pearson, type: value })}
            />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <SelectField
              labels={{ "": "None" }}
              label={pearson.mode === "Single" ? "Sample 1" : "Condition 1"}
              value={pearson.mode === "Single" ? pearson.sample1 : pearson.condition1}
              options={pool}
              onChange={(value) =>
                pearson.mode === "Single"
                  ? setPearson({ ...pearson, sample1: value })
                  : setPearson({ ...pearson, condition1: value })
              }
            />
            <SelectField
              labels={{ "": "None" }}
              label={pearson.mode === "Single" ? "Sample 2" : "Condition 2"}
              value={pearson.mode === "Single" ? pearson.sample2 : pearson.condition2}
              options={pool}
              onChange={(value) =>
                pearson.mode === "Single"
                  ? setPearson({ ...pearson, sample2: value })
                  : setPearson({ ...pearson, condition2: value })
              }
            />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <TextField
              label="Alias 1 (optional)"
              value={pearson.alias1}
              onChange={(value) => setPearson({ ...pearson, alias1: value })}
            />
            <TextField
              label="Alias 2 (optional)"
              value={pearson.alias2}
              onChange={(value) => setPearson({ ...pearson, alias2: value })}
            />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
          </div>
          <div className="flex flex-wrap gap-3">
          </div>
          {String(pearson.type || "").trim().toLowerCase() === "interactive" ? null : <SizeRow
            widthCm={pearson.widthCm}
            heightCm={pearson.heightCm}
            dpi={pearson.dpi}
            onWidthChange={(value) => setPearson({ ...pearson, widthCm: value })}
            onHeightChange={(value) => setPearson({ ...pearson, heightCm: value })}
            onDpiChange={(value) => setPearson({ ...pearson, dpi: value })}
          />}
        </div>
      );
    }

    const vennPool = venn.mode === "Single" ? samples : conditions;
    return (
      <div className="space-y-4">
        <div className="max-w-xs">
          <SelectField
            labels={{ "": "None" }}
            label="Mode"
            value={venn.mode}
            options={["Single", "Condition"]}
            onChange={(value) => setVenn({ ...venn, mode: value })}
          />
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <SelectField
            labels={{ "": "None" }}
            label={venn.mode === "Single" ? "Sample 1" : "Condition 1"}
            value={venn.first}
            options={vennPool}
            onChange={(value) => setVenn({ ...venn, first: value })}
          />
          <SelectField
            labels={{ "": "None" }}
            label={venn.mode === "Single" ? "Sample 2" : "Condition 2"}
            value={venn.second}
            options={vennPool}
            onChange={(value) => setVenn({ ...venn, second: value })}
          />
          <SelectField
            labels={{ "": "None" }}
            label={venn.mode === "Single" ? "Sample 3 (optional)" : "Condition 3 (optional)"}
            value={venn.third}
            options={["", ...vennPool]}
            onChange={(value) => setVenn({ ...venn, third: value })}
          />
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <TextField
            label="Alias 1 (optional)"
            value={venn.alias1}
            onChange={(value) => setVenn({ ...venn, alias1: value })}
          />
          <TextField
            label="Alias 2 (optional)"
            value={venn.alias2}
            onChange={(value) => setVenn({ ...venn, alias2: value })}
          />
          <TextField
            label="Alias 3 (optional)"
            value={venn.alias3}
            onChange={(value) => setVenn({ ...venn, alias3: value })}
          />
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
        </div>
        <div className="flex flex-wrap gap-3">
        </div>
        <SizeRow
          widthCm={venn.widthCm}
          heightCm={venn.heightCm}
          dpi={venn.dpi}
          onWidthChange={(value) => setVenn({ ...venn, widthCm: value })}
          onHeightChange={(value) => setVenn({ ...venn, heightCm: value })}
          onDpiChange={(value) => setVenn({ ...venn, dpi: value })}
        />
      </div>
    );
  }
}



function cmToIframeHeight(heightCm: number): number {
  const basePx = Number.isFinite(heightCm) ? (heightCm * 96) / 2.54 : (12 * 96) / 2.54;
  return Math.max(860, Math.round(basePx + 280));
}
