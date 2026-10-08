import { registerStyleStore, styleTemplate, withStyle } from "../../lib/plotStyles";
import { AssistantAppearanceMount, AssistantSelect } from "../../components/AssistantFields";
import PlotDownloadControls from "../../components/PlotDownloadControls";
import OptionsLayout from "../../components/OptionsLayout";
import PlotImage from "../../components/PlotImage";
import NotebookDownload, { type RenderedNotebook } from "../../components/NotebookDownload";
import { MATPLOTLIB_CONTROLS, MATPLOTLIB_NO_FRAME_CONTROLS, MATPLOTLIB_Y_DASHED_GRID_CONTROLS } from "../../lib/plotControlDefaults";
import { restorePlotDimensionCm, restorePlotDpi } from "../../lib/plotLimits";
import { SizeRow } from "../../components/PlotFields";
import CheckboxField from "../../components/CheckboxField";
import NumberField from "../../components/NumberField";
import { compactAdvancedPlotSettings as compactAdvancedSettings, migrateAdvancedSettingsMap } from "../../lib/plotSerialization";
import SummaryCard from "../../components/SummaryCard";
import { collectColumns, csvDataUrl, rowsToQuotedCsv as rowsToCsv } from "../../lib/tableData";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { fetchPlot } from "../../lib/fetchPlot";
import { buildPlotUrl, getCompletenessTables, getPeptideQuantityOptions, getQcPlotOptions, isAbortError } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import {
  coercePlotDownloadFormat,
  type PlotDownloadFormat,
  withPlotDownloadFilename,
  withPlotDownloadFormat,
} from "../../lib/plotDownload";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import { getAdvancedPlotMode } from "../../lib/appSettings";
import { IS_VIEWER_MODE } from "../../lib/appMode";
import AdvancedPlotOptions, {
  type AdvancedPlotControlDefaults,
  type AdvancedPlotVisibleControls,
} from "../../components/plots/AdvancedPlotOptions";
import type {
  AdvancedPlotSettings,
  AnnotationKind,
  CompletenessTab,
  CompletenessTablesResponse,
} from "../../lib/types";
import SelectField from "../../components/SelectField";
import PreviewTable from "../../components/PreviewTable";
import type { ContextMode } from "../../lib/types";
import LocalizationCutoffField from "../../components/LocalizationCutoffField";

type Props = {
  activeTab: CompletenessTab;
  onContextModeChange?: (mode: ContextMode | null) => void;
  notebook?: CompletenessNotebook | null;
  onNotebookChange?: (value: CompletenessNotebook) => void;
};

export type CompletenessNotebook = RenderedNotebook & { tab: "missingPlot" | "heatmap" };

type CompletenessKind = AnnotationKind | "peptide" | "precursor";
type AdvancedPlotState = Partial<Record<CompletenessTab, AdvancedPlotSettings>>;

function isAnnotationKind(kind: CompletenessKind): kind is AnnotationKind {
  return kind === "protein" || kind === "phospho" || kind === "phosprot";
}

// The page's appearance settings apply whether the panel is open or not:
// advanced mode only shows the panel, it never switches the settings.
function advancedParam(settings: AdvancedPlotSettings): string {
  const compacted = compactAdvancedSettings(settings);
  return Object.keys(compacted).length ? JSON.stringify(compacted) : "";
}

function withAdvancedParams(
  params: Record<string, string | number | boolean>,
  advanced: string
): Record<string, string | number | boolean> {
  return { ...params, advanced };
}

export default function CompletenessPage({ activeTab, onContextModeChange, notebook, onNotebookChange }: Props) {
  const fieldId = useId();
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("completeness.v1", {}),
    []
  );
  const persistedMissing = (persisted.missingPlot as Record<string, unknown>) ?? {};
  const persistedHeatmap = (persisted.heatmap as Record<string, unknown>) ?? {};
  const persistedTables = (persisted.tables as Record<string, unknown>) ?? {};
  // Versioned for the same reason as the QC page's.
  const persistedAdvanced: AdvancedPlotState = migrateAdvancedSettingsMap(IS_VIEWER_MODE ? {} : (persisted.advancedV2 as AdvancedPlotState) ?? {});
  const [kind, setKind] = useState<CompletenessKind>(() => {
    const value = String(persisted.kind ?? "protein").trim();
    if (value === "protein" || value === "phospho" || value === "phosprot" || value === "peptide" || value === "precursor") return value;
    return "protein";
  });
  const { datasets, availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [sampleOptions, setSampleOptions] = useState<string[]>([]);
  const [sampleDisplayLabels, setSampleDisplayLabels] = useState<Record<string, string>>({});
  const [sampleDisplayLabelsWithId, setSampleDisplayLabelsWithId] = useState<Record<string, string>>({});
  const [peptideQuantityColumns, setPeptideQuantityColumns] = useState<string[]>([]);
  const [peptideQuantityRequiresSelection, setPeptideQuantityRequiresSelection] = useState(false);
  const [peptideQuantityError, setPeptideQuantityError] = useState<string | null>(null);
  const [tableResult, setTableData] = useState<CompletenessTablesResponse | null>(null);
  const [tableResultUrl, setTableResultUrl] = useState("");
  const [tableNotebook, setTableNotebook] = useState<RenderedNotebook | null>(null);
  const tableRequest = useRef<AbortController | null>(null);
  const renderedNotebook = notebook ?? null;
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>(() =>
    coercePlotDownloadFormat(persisted.downloadFormat)
  );
  const [advancedModeEnabled, setAdvancedModeEnabled] = useState(() => getAdvancedPlotMode());
  const [advancedByTab, setAdvancedByTab] = useState<AdvancedPlotState>(() => persistedAdvanced);
  const [advancedRenderByTab, setAdvancedRenderByTab] = useState<AdvancedPlotState>(() => persistedAdvanced);

  const [missingPlot, setMissingPlot] = useState({
    quantityColumn: String(persistedMissing.quantityColumn ?? ""),
    header: true,
    text: Boolean(persistedMissing.text ?? true),
    binCount: Number(persistedMissing.binCount ?? 0),
    textSize: Number(persistedMissing.textSize ?? 8),
    color: String(persistedMissing.color ?? "#2563eb"),
    widthCm: restorePlotDimensionCm(persistedMissing.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedMissing.heightCm, 10),
    dpi: restorePlotDpi(persistedMissing.dpi, 300),
  });
  const [heatmap, setHeatmap] = useState({
    includeId: Boolean(persistedHeatmap.includeId ?? true),
    header: true,
    widthCm: restorePlotDimensionCm(persistedHeatmap.widthCm, 10),
    heightCm: restorePlotDimensionCm(persistedHeatmap.heightCm, 10),
    dpi: restorePlotDpi(persistedHeatmap.dpi, 300),
  });
  const [tables, setTables] = useState({
    includeId: Boolean(persistedTables.includeId ?? true),
    outlierThreshold: Number(persistedTables.outlierThreshold ?? 50),
  });

  const replayTab = activeTab === "tables" ? notebook?.tab ?? "missingPlot" : activeTab;
  const replayUrl = buildPlotUrl(
    `/api/plots/completeness/${kind}/${replayTab === "heatmap" ? "missing-heatmap" : "missing-value"}.png`,
    withAdvancedParams({ ...(replayTab === "heatmap" ? heatmap : missingPlot),
      tableIncludeId: tables.includeId, outlierThreshold: tables.outlierThreshold },
    advancedParam(advancedRenderByTab[replayTab] ?? styleTemplate() ?? {}))
  );
  const tableData = tableResultUrl === replayUrl ? tableResult : null;

  useEffect(() => {
    const nextState: Record<string, unknown> = {
      kind,
      downloadFormat,
      missingPlot,
      heatmap,
      tables,
    };
    if (!IS_VIEWER_MODE) {
      nextState.advancedV2 = advancedByTab;
    }
    writePersistedUiState("completeness.v1", nextState);
  }, [kind, downloadFormat, missingPlot, heatmap, tables, advancedByTab]);

  useEffect(() => {
    const refresh = () => setAdvancedModeEnabled(getAdvancedPlotMode());
    window.addEventListener("focus", refresh);
    window.addEventListener("storage", refresh);
    window.addEventListener("copylot:advancedPlotModeChanged", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("storage", refresh);
      window.removeEventListener("copylot:advancedPlotModeChanged", refresh);
    };
  }, []);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setAdvancedRenderByTab(advancedByTab);
    }, 350);
    return () => window.clearTimeout(timeout);
  }, [advancedByTab]);

  const activeKindOptions = useMemo<Array<{ value: CompletenessKind; label: string }>>(() => {
    if (activeTab !== "missingPlot") return kindOptions;
    const options: Array<{ value: CompletenessKind; label: string }> = [...kindOptions];
    if (datasets?.peptide) {
      options.push({ value: "peptide", label: "Peptide" });
      options.push({ value: "precursor", label: "Precursor" });
    }
    return options;
  }, [activeTab, kindOptions, datasets]);

  const loadTables = useCallback(async (signal?: AbortSignal, refresh = false) => {
    tableRequest.current?.abort();
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) {
      setTableData(null);
      setTableLoading(false);
      setTableError("Please upload a protein, phospho, or phosphoprotein dataset first.");
      return;
    }
    const controller = new AbortController();
    tableRequest.current = controller;
    const abort = () => controller.abort();
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) controller.abort();
    try {
      setTableLoading(true);
      setTableError(null);
      setTableData(null);
      setTableNotebook(null);
      let token = !refresh && renderedNotebook?.url === replayUrl ? renderedNotebook.token : null;
      if (!token) {
        const response = await fetchPlot(replayUrl, controller.signal);
        await response.arrayBuffer();
        const candidate = response.ok ? response.headers.get("X-CoPYlot-Notebook") ?? "" : "";
        token = /^[A-Za-z0-9_-]{32}$/.test(candidate) ? candidate : null;
      }
      const data = await getCompletenessTables(
        kind,
        {
          includeId: tables.includeId,
          outlierThreshold: tables.outlierThreshold,
          ...(token ? { snapshot: token } : {}),
        },
        { signal: controller.signal }
      );
      if (controller.signal.aborted) return;
      setTableData(data);
      setTableResultUrl(replayUrl);
      setTableNotebook({ url: replayUrl, token });
    } catch (err) {
      if (controller.signal.aborted || isAbortError(err)) return;
      setTableData(null);
      setTableError(err instanceof Error ? err.message : "Failed to load completeness tables");
    } finally {
      signal?.removeEventListener("abort", abort);
      if (!controller.signal.aborted) setTableLoading(false);
    }
  }, [availableKinds, kind, tables.includeId, tables.outlierThreshold, replayUrl, renderedNotebook]);

  useEffect(() => () => tableRequest.current?.abort(), []);

  useEffect(() => {
    if (activeKindOptions.length === 0) {
      setTableData(null);
      return;
    }
    if (!activeKindOptions.some((option) => option.value === kind)) {
      setKind(activeKindOptions[0].value);
    }
  }, [activeKindOptions, kind]);

  useEffect(() => {
    if ((kind !== "peptide" && kind !== "precursor") || !datasets?.peptide) {
      setPeptideQuantityColumns([]);
      setPeptideQuantityRequiresSelection(false);
      setPeptideQuantityError(null);
      return;
    }
    const controller = new AbortController();
    getPeptideQuantityOptions({ signal: controller.signal })
      .then((payload) => {
        setPeptideQuantityColumns(payload.columns);
        setPeptideQuantityRequiresSelection(payload.requiresSelection);
        setPeptideQuantityError(
          payload.columns.length === 0
            ? "No supported peptide abundance column was found in this dataset."
            : null
        );
        setMissingPlot((current) => {
          if (current.quantityColumn && payload.columns.includes(current.quantityColumn)) return current;
          return { ...current, quantityColumn: payload.defaultColumn ?? "" };
        });
      })
      .catch((error) => {
        if (isAbortError(error)) return;
        setPeptideQuantityColumns([]);
        setPeptideQuantityRequiresSelection(false);
        setPeptideQuantityError(
          error instanceof Error ? error.message : "Failed to load peptide abundance columns"
        );
      });
    return () => controller.abort();
  }, [kind, datasets?.peptide]);

  useEffect(() => {
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) {
      setSampleOptions([]);
      setSampleDisplayLabels({});
      setSampleDisplayLabelsWithId({});
      return;
    }
    const controller = new AbortController();
    getQcPlotOptions(kind, { signal: controller.signal })
      .then((payload) => {
        const samples = Array.from(new Set((payload.samples ?? []).map((value) => value.trim()).filter(Boolean)));
        setSampleOptions(samples);
        setSampleDisplayLabels(payload.sampleLabels ?? {});
        setSampleDisplayLabelsWithId(payload.sampleLabelsWithId ?? {});
      })
      .catch((error) => {
        if (isAbortError(error)) return;
        setSampleOptions([]);
        setSampleDisplayLabels({});
        setSampleDisplayLabelsWithId({});
      });
    return () => {
      controller.abort();
    };
  }, [kind, availableKinds]);

  useEffect(() => {
    if (!onContextModeChange) return;
    if (activeTab !== "missingPlot" && activeTab !== "heatmap" && activeTab !== "tables") {
      onContextModeChange(null);
      return;
    }
    if (activeTab === "tables") {
      onContextModeChange({ kind, outlierThreshold: tables.outlierThreshold, includeId: tables.includeId });
      return;
    }
    onContextModeChange({ kind });
  }, [activeTab, kind, tables.outlierThreshold, tables.includeId, onContextModeChange]);

  useEffect(() => {
    if (activeTab !== "tables") return;
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) return;
    const controller = new AbortController();
    loadTables(controller.signal);
    return () => controller.abort();
  }, [activeTab, kind, availableKinds, loadTables]);

  const activeAdvancedSettings = advancedByTab[activeTab] ?? styleTemplate() ?? {};
  // Named styles and "this style on every plot" (lib/plotStyles.ts) reach these settings here.
  const styleStoreState = useRef({ tab: activeTab, byTab: advancedByTab });
  useEffect(() => { styleStoreState.current = { tab: activeTab, byTab: advancedByTab }; }, [activeTab, advancedByTab]);
  useEffect(() => registerStyleStore("completeness", {
    active: () => styleStoreState.current.byTab[styleStoreState.current.tab] ?? styleTemplate() ?? {},
    setActive: (settings) => setAdvancedByTab((prev) => ({ ...prev, [styleStoreState.current.tab]: settings })),
    setAll: (style) => {
      setAdvancedByTab((prev) => Object.fromEntries(Object.entries(prev).map(([tab, value]) => [tab, withStyle(value, style)])));
      return Object.keys(styleStoreState.current.byTab).length;
    },
  }), []);
  const activeSampleDisplayLabels = useMemo(() => {
    const rawLabels = Object.fromEntries(sampleOptions.map((sample) => [sample, sample]));
    if (activeTab === "heatmap") {
      return heatmap.includeId ? sampleDisplayLabelsWithId : sampleDisplayLabels;
    }
    return rawLabels;
  }, [activeTab, heatmap.includeId, sampleDisplayLabels, sampleDisplayLabelsWithId, sampleOptions]);
  const activeAdvancedVisibleControls = useMemo<AdvancedPlotVisibleControls>(() => {
    if (activeTab === "missingPlot") {
      return {
        legendControls: false,
        conditionLabels: false,
        sampleLabels: false,
        conditionColors: false,
        // `_missing_value_plot_from_matrix` reads both: `barColor` for the bars
        // and `valueLabelSize` for the count printed over each one. Neither was
        // offered here, so the plot's own colour could not be changed anywhere.
        barColor: true,
        valueLabels: true,
      };
    }
    if (activeTab === "heatmap") {
      return {
        legendControls: false,
        conditionLabels: false,
        sampleLabels: true,
        conditionColors: false,
      };
    }
    return {};
  }, [activeTab]);
  // The plot as drawn: the missing value plot has a dashed y grid, the missing
  // value heatmap has no frame at all.
  const activeAdvancedControlDefaults = useMemo<AdvancedPlotControlDefaults>(() => {
    if (activeTab === "missingPlot") return MATPLOTLIB_Y_DASHED_GRID_CONTROLS;
    if (activeTab === "heatmap") return MATPLOTLIB_NO_FRAME_CONTROLS;
    return MATPLOTLIB_CONTROLS;
  }, [activeTab]);

  const plotView = useMemo(() => {
    if (activeTab === "missingPlot") {
      if ((kind === "peptide" || kind === "precursor") && (!missingPlot.quantityColumn || peptideQuantityError)) {
        return null;
      }
      return {
        title: "Missing Value Plot",
        filename: `completeness_missing_plot_${kind}.png`,
        url: replayUrl,
      };
    }
    if (activeTab === "heatmap") {
      return {
        title: "Missing Value Heatmap",
        filename: `completeness_missing_heatmap_${kind}.png`,
        url: replayUrl,
      };
    }
    return null;
  }, [activeTab, kind, missingPlot.quantityColumn, replayUrl, peptideQuantityError]);
  const plotDownloadUrl = useMemo(() => {
    if (!plotView) return "";
    return withPlotDownloadFormat(plotView.url, downloadFormat);
  }, [plotView, downloadFormat]);
  const plotDownloadFilename = useMemo(() => {
    if (!plotView) return "";
    return withPlotDownloadFilename(plotView.filename, downloadFormat);
  }, [plotView, downloadFormat]);

  const sampleCsvUrl = useMemo(() => {
    if (!tableData || tableData.sampleSummary.length === 0) return null;
    const columns = collectColumns(tableData.sampleSummary);
    return csvDataUrl(rowsToCsv(tableData.sampleSummary, columns));
  }, [tableData]);

  const featureCsvUrl = useMemo(() => {
    if (!tableData || tableData.featureSummary.length === 0) return null;
    const columns = collectColumns(tableData.featureSummary);
    return csvDataUrl(rowsToCsv(tableData.featureSummary, columns));
  }, [tableData]);

  const outlierCsvUrl = useMemo(() => {
    if (!tableData || tableData.outliers.length === 0) return null;
    const rows = tableData.outliers.map((sample) => ({ Sample: sample }));
    return csvDataUrl(rowsToCsv(rows, ["Sample"]));
  }, [tableData]);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Data Completeness</h2>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div>
            <label htmlFor={fieldId} className="mb-2 block text-sm font-medium text-slate-700">Dataset level</label>
            <AssistantSelect
              id={fieldId}
              value={kind}
              onChange={(e) => setKind(e.target.value as CompletenessKind)}
              disabled={activeKindOptions.length === 0}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
            >
              {activeKindOptions.length === 0 ? (
                <option value="">No dataset available</option>
              ) : (
                activeKindOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))
              )}
            </AssistantSelect>
          </div>
          <LocalizationCutoffField kind={kind} />
        </div>
      </section>

      {activeKindOptions.length === 0 ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
          Upload a protein, phospho, phosphoprotein, or peptide dataset in the Data tab to enable completeness plots.
        </section>
      ) : null}

      {activeKindOptions.length > 0 ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Options</h3>
        <div className="mt-4">{renderOptions()}</div>
        {(kind === "peptide" || kind === "precursor") && peptideQuantityError ? (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {peptideQuantityError}
          </div>
        ) : null}
        {(kind === "peptide" || kind === "precursor") && peptideQuantityRequiresSelection && !missingPlot.quantityColumn ? (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Select which abundance column should be used before rendering this plot.
          </div>
        ) : null}
      </section>
      ) : null}

      {activeKindOptions.length > 0 && activeTab !== "tables" ? (
        <AssistantAppearanceMount visible={advancedModeEnabled}>
        <AdvancedPlotOptions
          key={activeTab}
          value={activeAdvancedSettings}
          onChange={(next) => setAdvancedByTab((prev) => ({ ...prev, [activeTab]: next }))}
          sampleOptions={sampleOptions}
          sampleDisplayLabels={activeSampleDisplayLabels}
          visibleControls={activeAdvancedVisibleControls}
          controlDefaults={activeAdvancedControlDefaults}
        />
        </AssistantAppearanceMount>
      ) : null}

      {activeKindOptions.length > 0 && plotView ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">{plotView.title}</h3>
            <div className="flex flex-wrap items-center gap-2">
              <PlotDownloadControls label="Plot" format={downloadFormat} onFormatChange={setDownloadFormat}
                href={plotDownloadUrl} filename={plotDownloadFilename} />
              <NotebookDownload plotUrl={plotView.url} rendered={renderedNotebook} />
            </div>
          </div>
          <div className="mt-4">
            <PlotImage url={plotView.url} alt={plotView.title}
              onRendered={(url, token) => {
                if (activeTab !== "tables") onNotebookChange?.({ url, token, tab: activeTab });
              }} />
          </div>
        </section>
      ) : null}

      {activeKindOptions.length > 0 && activeTab === "tables" && isAnnotationKind(kind) ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">Missing Value Tables</h3>
            <button
              type="button"
              onClick={() => void loadTables(undefined, true)}
              disabled={tableLoading}
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {tableLoading ? "Refreshing..." : "Refresh"}
            </button>
          </div>

          {tableError ? (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {tableError}
            </div>
          ) : null}

          {tableData ? (
            <div className="mt-4 space-y-6">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <SummaryCard label="Overall Missing Values" value={`${tableData.overallMissingPercent}%`} />
                <SummaryCard label="Outlier Threshold" value={`${tableData.outlierThreshold}%`} />
                <SummaryCard label="Outlier Samples" value={String(tableData.outliers.length)} />
              </div>
              {tableData.excludedAllMissingCount > 0 ? (
                <p className="text-xs text-slate-500">
                  {tableData.excludedAllMissingCount} feature{tableData.excludedAllMissingCount === 1 ? "" : "s"} with no
                  value in any selected sample {tableData.excludedAllMissingCount === 1 ? "is" : "are"} excluded from the
                  plot and the tables.
                </p>
              ) : null}

              <section>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <h4 className="text-base font-semibold text-slate-900">Sample-level Missing Values</h4>
                  <div className="flex flex-wrap items-center gap-2">
                  {sampleCsvUrl ? (
                    <a
                      href={sampleCsvUrl}
                      download={`completeness_sample_summary_${kind}.csv`}
                      className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                    >
                      Download CSV
                    </a>
                  ) : null}
                  <NotebookDownload plotUrl={replayUrl} rendered={tableNotebook} />
                  </div>
                </div>
                <PreviewTable rows={tableData.sampleSummary} emptyText="No sample summary rows available." />
              </section>

              <section>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <h4 className="text-base font-semibold text-slate-900">Outliers by Missing Value %</h4>
                  <div className="flex flex-wrap items-center gap-2">
                  {outlierCsvUrl ? (
                    <a
                      href={outlierCsvUrl}
                      download={`completeness_outliers_${kind}.csv`}
                      className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                    >
                      Download CSV
                    </a>
                  ) : null}
                  <NotebookDownload plotUrl={replayUrl} rendered={tableNotebook} />
                  </div>
                </div>
                {tableData.outliers.length > 0 ? (
                  <PreviewTable
                    rows={tableData.outliers.map((sample) => ({ Sample: sample }))}
                    emptyText="No outliers."
                  />
                ) : (
                  <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                    No samples exceed the selected outlier threshold.
                  </div>
                )}
              </section>

              <section>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <h4 className="text-base font-semibold text-slate-900">Feature-level Missing Value Distribution</h4>
                  <div className="flex flex-wrap items-center gap-2">
                  {featureCsvUrl ? (
                    <a
                      href={featureCsvUrl}
                      download={`completeness_feature_summary_${kind}.csv`}
                      className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                    >
                      Download CSV
                    </a>
                  ) : null}
                  <NotebookDownload plotUrl={replayUrl} rendered={tableNotebook} />
                  </div>
                </div>
                <PreviewTable rows={tableData.featureSummary} emptyText="No feature summary rows available."
                  labels={{ Counts: "Features (n)", "%_missing_values": "Features (%)" }} />
              </section>
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              {tableLoading ? "Loading table data..." : "No table data loaded yet."}
            </div>
          )}
        </section>
      ) : null}
    </div>
  );

  function renderOptions() {
    if (activeTab === "missingPlot") {
      return (
        <OptionsLayout order="toggles-fields-size"
          toggles={[
            <CheckboxField assistant={false} key="text" label="Toggle Text" checked={missingPlot.text} onChange={(v) => setMissingPlot({ ...missingPlot, text: v })} />,
          ]}
          fields={[
            ...((kind === "peptide" || kind === "precursor")
              ? [
                  <SelectField
                    key="quantity-column"
                    label="Abundance Column"
                    value={missingPlot.quantityColumn}
                    onChange={(value) => setMissingPlot({ ...missingPlot, quantityColumn: value })}
                    options={peptideQuantityColumns}
                    placeholder={peptideQuantityRequiresSelection ? "Select abundance column" : undefined}
                  />,
                ]
              : []),
            <NumberField assistant={false} key="bin" label="Bin missing values" value={missingPlot.binCount} onChange={(v) => setMissingPlot({ ...missingPlot, binCount: Math.max(0, Math.round(v)) })} />,
          ]}
          size={
            <SizeRow
              dpi={missingPlot.dpi}
              heightCm={missingPlot.heightCm}
              widthCm={missingPlot.widthCm}
              onDpiChange={(v) => setMissingPlot({ ...missingPlot, dpi: v })}
              onHeightChange={(v) => setMissingPlot({ ...missingPlot, heightCm: v })}
              onWidthChange={(v) => setMissingPlot({ ...missingPlot, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "heatmap") {
      return (
        <OptionsLayout order="toggles-fields-size"
          toggles={[
            <CheckboxField assistant={false} key="id" label="Toggle IDs" checked={heatmap.includeId} onChange={(v) => setHeatmap({ ...heatmap, includeId: v })} />,
          ]}
          size={
            <SizeRow
              dpi={heatmap.dpi}
              heightCm={heatmap.heightCm}
              widthCm={heatmap.widthCm}
              onDpiChange={(v) => setHeatmap({ ...heatmap, dpi: v })}
              onHeightChange={(v) => setHeatmap({ ...heatmap, heightCm: v })}
              onWidthChange={(v) => setHeatmap({ ...heatmap, widthCm: v })}
            />
          }
        />
      );
    }

    return (
      <OptionsLayout order="toggles-fields-size"
        toggles={[
          <CheckboxField assistant={false} key="id" label="Toggle IDs" checked={tables.includeId} onChange={(v) => setTables({ ...tables, includeId: v })} />,
        ]}
        fields={[
          <NumberField assistant={false}
            key="threshold"
            label="Outlier Threshold (%)"
            value={tables.outlierThreshold}
            onChange={(v) => setTables({ ...tables, outlierThreshold: Math.max(0, Math.min(100, v)) })}
          />,
        ]}
        size={<div />}
      />
    );
  }
}
