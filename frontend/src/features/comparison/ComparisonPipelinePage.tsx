import { SizeRow } from "../../components/PlotFields";
import PlotDownloadControls from "../../components/PlotDownloadControls";
import PlotImage from "../../components/PlotImage";
import InteractivePlot from "../../components/InteractivePlot";
import NotebookDownload, { type RenderedNotebook } from "../../components/NotebookDownload";
import { withoutStaticSize } from "../../lib/plotRenderType";
import { restorePlotDimensionCm, restorePlotDpi, iframeHeightForPlot } from "../../lib/plotLimits";
import { AssistantSelect } from "../../components/AssistantFields";
import { collectColumns } from "../../lib/tableData";
import { csvDataUrl, rowsToCsv } from "../../lib/tableData";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, getComparisonOptions, getComparisonTable, isAbortError } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import {
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
import NumberField from "../../components/NumberField";
import type { ContextMode } from "../../lib/types";
import LocalizationCutoffField from "../../components/LocalizationCutoffField";

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
  const [notebook, setNotebook] = useState<RenderedNotebook | null>(null);
  const [tableSnapshot, setTableSnapshot] = useState<string | null>(null);
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
    // Condition mode: how many samples of a condition must have a value for a
    // feature to count as present there. 1 is the long-standing behaviour.
    minPresent: Math.max(1, Math.round(Number(persistedVenn.minPresent ?? 1)) || 1),
    color1: String(persistedVenn.color1 ?? "#1f77b4"),
    color2: String(persistedVenn.color2 ?? "#ff7f0e"),
    color3: String(persistedVenn.color3 ?? "#2ca02c"),
    header: true,
    widthCm: restorePlotDimensionCm(persistedVenn.widthCm, 15),
    heightCm: restorePlotDimensionCm(persistedVenn.heightCm, 12),
    dpi: restorePlotDpi(persistedVenn.dpi, 300),
  });
  const [pearsonInteractiveSessionNonce] = useState(() => Date.now());
  // The alias fields start out as the `WT_1`-style label of the selected
  // sample (the name every QC plot uses), and are overwritten whenever the
  // selection changes; the user can still type any alias afterwards.
  const sampleAlias = (sample: string) => options?.sampleLabels?.[sample] ?? "";
  // An alias that is still the automatic sample label is dropped when the
  // mode changes, so condition sets are not labelled "A_1"; a typed alias stays.
  const keepTypedAlias = (alias: string, sample: string) => (alias && alias === sampleAlias(sample) ? "" : alias);

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
      const labels = options.sampleLabels ?? {};
      const alias1 = (prev.mode === "Single" && sample1 !== prev.sample1 ? "" : prev.alias1)
        || (prev.mode === "Single" ? labels[sample1] ?? "" : "");
      const alias2 = (prev.mode === "Single" && sample2 !== prev.sample2 ? "" : prev.alias2)
        || (prev.mode === "Single" ? labels[sample2] ?? "" : "");
      return { ...prev, sample1, sample2, condition1, condition2, alias1, alias2 };
    });
  }, [options, pearson.mode]);

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
      const labels = venn.mode === "Single" ? options.sampleLabels ?? {} : {};
      const knownSelections = new Set([...options.samples, ...options.conditions]);
      return {
        ...prev, first, second, third,
        alias1: (knownSelections.has(prev.first) ? prev.alias1 : "") || (labels[first] ?? ""),
        alias2: (knownSelections.has(prev.second) ? prev.alias2 : "") || (labels[second] ?? ""),
        alias3: (third && knownSelections.has(prev.third) ? prev.alias3 : "") || (third ? labels[third] ?? "" : ""),
      };
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
      ...(venn.mode === "Condition" ? { minPresent: venn.minPresent } : {}),
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

  const plotToken = notebook?.url === plotView?.url ? notebook?.token : null;
  const tableRequest = useMemo<TableRequest>(() => {
    void advancedPlotSignal;
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
        params: plotToken ? { ...params, snapshot: plotToken } : params,
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
      ...(venn.mode === "Condition" ? { minPresent: venn.minPresent } : {}),
    };
    return {
      tab: "venn",
      params: plotToken ? { ...params, snapshot: plotToken } : params,
    };
  }, [
    advancedPlotSignal,
    plotToken,
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
    venn.minPresent,
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
    setTableSnapshot(null);
    getComparisonTable(kind, tableRequest.tab, tableRequest.params, { signal: controller.signal })
      .then((payload) => {
        if (controller.signal.aborted) return;
        setTableRows(payload.rows ?? []);
        setTableSnapshot(typeof tableRequest.params.snapshot === 'string' ? tableRequest.params.snapshot : null);
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
    return csvDataUrl(rowsToCsv(tableRows, columns));
  }, [tableRows]);

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
          <LocalizationCutoffField kind={kind} />
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
                <PlotDownloadControls label="Plot" format={downloadFormat} onFormatChange={setDownloadFormat}
                  href={plotDownloadUrl} filename={plotDownloadFilename} />
                <NotebookDownload plotUrl={plotView.url} rendered={notebook} />
              </div>
            ) : plotView?.renderMode === "html" ? (
              <div className="flex items-center gap-2">
              <a
                href={plotView.url}
                target="_blank"
                rel="noreferrer"
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Open Interactive Plot
              </a>
              <NotebookDownload plotUrl={plotView.url} rendered={notebook} />
              </div>
            ) : null}
          </div>

          {plotView ? (
            <div className="mt-4">
              {plotView.renderMode === "image" ? (
                <PlotImage url={plotView.url} alt={plotView.title}
                  onRendered={(url, token) => setNotebook({ url, token })} />
              ) : (
                <InteractivePlot url={plotView.url} title={plotView.title}
                  height={`max(${cmToIframeHeight(12)}px, 78vh)`}
                  onRendered={(url, token) => setNotebook({ url, token })} />
              )}
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              {modePool.length === 0
                ? "No selectable samples/conditions are available for this dataset."
                : "Select valid entries to render the plot."}
            </div>
          )}

        </section>
      ) : null}

      {kindOptions.length > 0 ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">Summary Table</h3>
            {tableCsvUrl ? (
              <div className="flex items-center gap-2">
              <a
                href={tableCsvUrl}
                download={`comparison_${activeTab}_${kind}.csv`}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download CSV
              </a>
              {plotView ? <NotebookDownload plotUrl={plotView.url}
                rendered={!tableLoading && !tableError && tableSnapshot === plotToken ? notebook : null} /> : null}
              </div>
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
              <PreviewTable rows={tableRows} emptyText="No table rows available for the current selection." plotSummary />
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
              onChange={(value) => setPearson({
                ...pearson, mode: value,
                alias1: keepTypedAlias(pearson.alias1, pearson.sample1),
                alias2: keepTypedAlias(pearson.alias2, pearson.sample2),
              })}
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
                  ? setPearson({ ...pearson, sample1: value, alias1: sampleAlias(value) })
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
                  ? setPearson({ ...pearson, sample2: value, alias2: sampleAlias(value) })
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
            onChange={(value) => setVenn({
              ...venn, mode: value,
              alias1: keepTypedAlias(venn.alias1, venn.first),
              alias2: keepTypedAlias(venn.alias2, venn.second),
              alias3: keepTypedAlias(venn.alias3, venn.third),
            })}
          />
        </div>
        {venn.mode === "Condition" ? (
          <div className="max-w-xs">
            <NumberField
              label="Minimum values per condition"
              value={venn.minPresent}
              step={1}
              validate={(value) => (Number.isInteger(value) && value >= 1 ? null : "Use a whole number of at least 1.")}
              onChange={(value) => setVenn({ ...venn, minPresent: value })}
            />
          </div>
        ) : null}
        <div className="grid gap-4 lg:grid-cols-3">
          <SelectField
            labels={{ "": "None" }}
            label={venn.mode === "Single" ? "Sample 1" : "Condition 1"}
            value={venn.first}
            options={vennPool}
            onChange={(value) => setVenn({ ...venn, first: value, ...(venn.mode === "Single" ? { alias1: sampleAlias(value) } : {}) })}
          />
          <SelectField
            labels={{ "": "None" }}
            label={venn.mode === "Single" ? "Sample 2" : "Condition 2"}
            value={venn.second}
            options={vennPool}
            onChange={(value) => setVenn({ ...venn, second: value, ...(venn.mode === "Single" ? { alias2: sampleAlias(value) } : {}) })}
          />
          <SelectField
            labels={{ "": "None" }}
            label={venn.mode === "Single" ? "Sample 3 (optional)" : "Condition 3 (optional)"}
            value={venn.third}
            options={["", ...vennPool]}
            onChange={(value) => setVenn({ ...venn, third: value, ...(venn.mode === "Single" ? { alias3: sampleAlias(value) } : {}) })}
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
  return iframeHeightForPlot(heightCm, { fallbackCm: 12, minPx: 860, paddingPx: 280 });
}
