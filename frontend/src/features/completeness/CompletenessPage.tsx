import SelectField from "../../components/SelectField";
import { SizeRow, Checkbox, NumericField } from "../../components/QcFields";
import { compactMap, compactTextElement } from "../../lib/plotSerialization";
import SummaryCard from "../../components/SummaryCard";
import { collectColumns, rowsToQuotedCsv as rowsToCsv } from "../../lib/tableData";
import { useId, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, getCompletenessTables, getPeptideQuantityOptions, getQcPlotOptions, isAbortError } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import {
  PLOT_DOWNLOAD_FORMAT_OPTIONS,
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

type Props = {
  activeTab: CompletenessTab;
  onContextModeChange?: (mode: string) => void;
};

type CompletenessKind = AnnotationKind | "peptide" | "precursor";
type AdvancedPlotState = Partial<Record<CompletenessTab, AdvancedPlotSettings>>;

function isAnnotationKind(kind: CompletenessKind): kind is AnnotationKind {
  return kind === "protein" || kind === "phospho" || kind === "phosprot";
}

function compactAdvancedSettings(settings: AdvancedPlotSettings): AdvancedPlotSettings {
  const next: AdvancedPlotSettings = {};
  const title = settings.title?.trim();
  const xLabel = settings.xLabel?.trim();
  const yLabel = settings.yLabel?.trim();
  const backgroundColor = settings.backgroundColor?.trim();
  const plotTheme = settings.plotTheme?.trim();
  const axisLineColor = settings.axisLineColor?.trim();
  const axisLineStyle = settings.axisLineStyle?.trim();
  const gridLineAxis = settings.gridLineAxis?.trim();
  const gridLineColor = settings.gridLineColor?.trim();
  const gridLineStyle = settings.gridLineStyle?.trim();
  const titleElement = compactTextElement(settings.titleElement);
  const xLabelElement = compactTextElement(settings.xLabelElement);
  const yLabelElement = compactTextElement(settings.yLabelElement);

  if (title) next.title = title;
  if (xLabel) next.xLabel = xLabel;
  if (yLabel) next.yLabel = yLabel;
  if (titleElement) {
    next.titleElement = titleElement;
    if (titleElement.text) next.title = titleElement.text;
    if (titleElement.size) next.titleSize = titleElement.size;
  }
  if (xLabelElement) {
    next.xLabelElement = xLabelElement;
    if (xLabelElement.text) next.xLabel = xLabelElement.text;
  }
  if (yLabelElement) {
    next.yLabelElement = yLabelElement;
    if (yLabelElement.text) next.yLabel = yLabelElement.text;
  }
  if (settings.titleSize && settings.titleSize > 0) next.titleSize = settings.titleSize;
  if (settings.axisLabelSize && settings.axisLabelSize > 0) next.axisLabelSize = settings.axisLabelSize;
  if (settings.tickLabelSize && settings.tickLabelSize > 0) next.tickLabelSize = settings.tickLabelSize;
  if (settings.xTickLabelSize && settings.xTickLabelSize > 0) next.xTickLabelSize = settings.xTickLabelSize;
  if (settings.yTickLabelSize && settings.yTickLabelSize > 0) next.yTickLabelSize = settings.yTickLabelSize;
  if (Number.isFinite(settings.xTickLabelRotation)) next.xTickLabelRotation = settings.xTickLabelRotation;
  if (Number.isFinite(settings.yTickLabelRotation)) next.yTickLabelRotation = settings.yTickLabelRotation;
  if (settings.textXOffset) next.textXOffset = settings.textXOffset;
  if (settings.textYOffset) next.textYOffset = settings.textYOffset;
  if (backgroundColor) next.backgroundColor = backgroundColor;
  if (typeof settings.transparentBackground === "boolean") next.transparentBackground = settings.transparentBackground;
  if (plotTheme && plotTheme !== "default") next.plotTheme = plotTheme;
  if (typeof settings.axisLineVisible === "boolean") next.axisLineVisible = settings.axisLineVisible;
  if (axisLineColor) next.axisLineColor = axisLineColor;
  if (settings.axisLineWidth && settings.axisLineWidth > 0) next.axisLineWidth = settings.axisLineWidth;
  if (axisLineStyle && axisLineStyle !== "solid") next.axisLineStyle = axisLineStyle;
  if (typeof settings.axisLineTop === "boolean") next.axisLineTop = settings.axisLineTop;
  if (typeof settings.axisLineRight === "boolean") next.axisLineRight = settings.axisLineRight;
  if (typeof settings.axisLineBottom === "boolean") next.axisLineBottom = settings.axisLineBottom;
  if (typeof settings.axisLineLeft === "boolean") next.axisLineLeft = settings.axisLineLeft;
  if (typeof settings.gridLineVisible === "boolean") next.gridLineVisible = settings.gridLineVisible;
  if (gridLineAxis && gridLineAxis !== "y") next.gridLineAxis = gridLineAxis;
  if (gridLineColor) next.gridLineColor = gridLineColor;
  if (settings.gridLineWidth && settings.gridLineWidth > 0) next.gridLineWidth = settings.gridLineWidth;
  if (gridLineStyle && gridLineStyle !== "solid") next.gridLineStyle = gridLineStyle;

  const sampleLabels = compactMap(settings.sampleLabels);
  if (sampleLabels) next.sampleLabels = sampleLabels;
  return next;
}

function advancedParam(settings: AdvancedPlotSettings, enabled: boolean): string {
  if (!enabled) return "";
  const compacted = compactAdvancedSettings(settings);
  return Object.keys(compacted).length ? JSON.stringify(compacted) : "";
}

function withAdvancedParams(
  params: Record<string, string | number | boolean>,
  advanced: string
): Record<string, string | number | boolean> {
  return { ...params, advanced };
}

export default function CompletenessPage({ activeTab, onContextModeChange }: Props) {
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("completeness.v1", {}),
    []
  );
  const persistedMissing = (persisted.missingPlot as Record<string, unknown>) ?? {};
  const persistedHeatmap = (persisted.heatmap as Record<string, unknown>) ?? {};
  const persistedTables = (persisted.tables as Record<string, unknown>) ?? {};
  const persistedAdvanced = IS_VIEWER_MODE ? {} : (persisted.advanced as AdvancedPlotState) ?? {};
  const [kind, setKind] = useState<CompletenessKind>(() => {
    const value = String(persisted.kind ?? "protein").trim();
    if (value === "protein" || value === "phospho" || value === "phosprot" || value === "peptide" || value === "precursor") return value;
    return "protein";
  });
  const { datasets, availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [imageError, setImageError] = useState<string | null>(null);
  const [sampleOptions, setSampleOptions] = useState<string[]>([]);
  const [sampleDisplayLabels, setSampleDisplayLabels] = useState<Record<string, string>>({});
  const [sampleDisplayLabelsWithId, setSampleDisplayLabelsWithId] = useState<Record<string, string>>({});
  const [peptideQuantityColumns, setPeptideQuantityColumns] = useState<string[]>([]);
  const [peptideQuantityRequiresSelection, setPeptideQuantityRequiresSelection] = useState(false);
  const [peptideQuantityError, setPeptideQuantityError] = useState<string | null>(null);
  const [tableData, setTableData] = useState<CompletenessTablesResponse | null>(null);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>(() => {
    const value = String(persisted.downloadFormat ?? "png").trim();
    return value === "jpg" || value === "webp" || value === "pdf" ? value : "png";
  });
  const [advancedModeEnabled, setAdvancedModeEnabled] = useState(() => getAdvancedPlotMode());
  const [advancedByTab, setAdvancedByTab] = useState<AdvancedPlotState>(() => persistedAdvanced);
  const [advancedRenderByTab, setAdvancedRenderByTab] = useState<AdvancedPlotState>(() => persistedAdvanced);

  const [missingPlot, setMissingPlot] = useState({
    quantityColumn: String(persistedMissing.quantityColumn ?? ""),
    header: Boolean(persistedMissing.header ?? true),
    text: Boolean(persistedMissing.text ?? true),
    binCount: Number(persistedMissing.binCount ?? 0),
    textSize: Number(persistedMissing.textSize ?? 8),
    color: String(persistedMissing.color ?? "#2563eb"),
    widthCm: Number(persistedMissing.widthCm ?? 20),
    heightCm: Number(persistedMissing.heightCm ?? 10),
    dpi: Number(persistedMissing.dpi ?? 300),
  });
  const [heatmap, setHeatmap] = useState({
    includeId: Boolean(persistedHeatmap.includeId ?? true),
    header: Boolean(persistedHeatmap.header ?? true),
    widthCm: Number(persistedHeatmap.widthCm ?? 10),
    heightCm: Number(persistedHeatmap.heightCm ?? 10),
    dpi: Number(persistedHeatmap.dpi ?? 300),
  });
  const [tables, setTables] = useState({
    includeId: Boolean(persistedTables.includeId ?? true),
    outlierThreshold: Number(persistedTables.outlierThreshold ?? 50),
  });

  useEffect(() => {
    const nextState: Record<string, unknown> = {
      kind,
      downloadFormat,
      missingPlot,
      heatmap,
      tables,
    };
    if (!IS_VIEWER_MODE) {
      nextState.advanced = advancedByTab;
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

  const loadTables = useCallback(async (signal?: AbortSignal) => {
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) {
      setTableData(null);
      setTableError("Please upload a protein, phospho, or phosphoprotein dataset first.");
      return;
    }
    try {
      setTableLoading(true);
      setTableError(null);
      const data = await getCompletenessTables(
        kind,
        {
          includeId: tables.includeId,
          outlierThreshold: tables.outlierThreshold,
        },
        { signal }
      );
      setTableData(data);
    } catch (err) {
      if (isAbortError(err)) return;
      setTableData(null);
      setTableError(err instanceof Error ? err.message : "Failed to load completeness tables");
    } finally {
      if (!signal?.aborted) setTableLoading(false);
    }
  }, [availableKinds, kind, tables.includeId, tables.outlierThreshold]);

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
      onContextModeChange("");
      return;
    }
    if (activeTab === "tables") {
      onContextModeChange(
        `kind=${kind}|outlierThreshold=${tables.outlierThreshold}|includeId=${tables.includeId ? "true" : "false"}`
      );
      return;
    }
    onContextModeChange(`kind=${kind}`);
  }, [activeTab, kind, tables.outlierThreshold, tables.includeId, onContextModeChange]);

  useEffect(() => {
    if (activeTab !== "tables") return;
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) return;
    const controller = new AbortController();
    loadTables(controller.signal);
    return () => controller.abort();
  }, [activeTab, kind, availableKinds, loadTables]);

  const activeAdvancedSettings = advancedByTab[activeTab] ?? {};
  const activeAdvancedRenderSettings = useMemo(
    () => advancedRenderByTab[activeTab] ?? {},
    [activeTab, advancedRenderByTab]
  );
  const activeSampleDisplayLabels = useMemo(() => {
    const rawLabels = Object.fromEntries(sampleOptions.map((sample) => [sample, sample]));
    if (activeTab === "heatmap") {
      return heatmap.includeId ? sampleDisplayLabelsWithId : sampleDisplayLabels;
    }
    return rawLabels;
  }, [activeTab, heatmap.includeId, sampleDisplayLabels, sampleDisplayLabelsWithId, sampleOptions]);
  const activeAdvancedParam = useMemo(
    () => advancedParam(activeAdvancedRenderSettings, advancedModeEnabled),
    [activeAdvancedRenderSettings, advancedModeEnabled]
  );
  const activeAdvancedVisibleControls = useMemo<AdvancedPlotVisibleControls>(() => {
    if (activeTab === "missingPlot") {
      return {
        legendControls: false,
        conditionLabels: false,
        sampleLabels: false,
        conditionColors: false,
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
  const activeAdvancedControlDefaults = useMemo<AdvancedPlotControlDefaults>(() => {
    if (activeTab === "missingPlot") {
      return {
        gridLineVisible: true,
        gridLineAxis: "y",
        gridLineColor: "#b0b0b0",
        gridLineStyle: "dashed",
        gridLineWidth: 0.8,
        axisLineLeft: true,
        axisLineRight: true,
        axisLineBottom: true,
        axisLineTop: true,
      };
    }
    return {
      gridLineVisible: false,
      gridLineAxis: "y",
      gridLineStyle: "dashed",
      axisLineLeft: true,
      axisLineRight: true,
      axisLineBottom: true,
      axisLineTop: true,
    };
  }, [activeTab]);

  const plotView = useMemo(() => {
    if (activeTab === "missingPlot") {
      if ((kind === "peptide" || kind === "precursor") && (!missingPlot.quantityColumn || peptideQuantityError)) {
        return null;
      }
      return {
        title: "Missing Value Plot",
        filename: `completeness_missing_plot_${kind}.png`,
        url: buildPlotUrl(
          `/api/plots/completeness/${kind}/missing-value.png`,
          withAdvancedParams(missingPlot, activeAdvancedParam)
        ),
      };
    }
    if (activeTab === "heatmap") {
      return {
        title: "Missing Value Heatmap",
        filename: `completeness_missing_heatmap_${kind}.png`,
        url: buildPlotUrl(
          `/api/plots/completeness/${kind}/missing-heatmap.png`,
          withAdvancedParams(heatmap, activeAdvancedParam)
        ),
      };
    }
    return null;
  }, [activeTab, kind, missingPlot, heatmap, activeAdvancedParam, peptideQuantityError]);
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
    return `data:text/csv;charset=utf-8,${encodeURIComponent(rowsToCsv(tableData.sampleSummary, columns))}`;
  }, [tableData]);

  const featureCsvUrl = useMemo(() => {
    if (!tableData || tableData.featureSummary.length === 0) return null;
    const columns = collectColumns(tableData.featureSummary);
    return `data:text/csv;charset=utf-8,${encodeURIComponent(rowsToCsv(tableData.featureSummary, columns))}`;
  }, [tableData]);

  const outlierCsvUrl = useMemo(() => {
    if (!tableData || tableData.outliers.length === 0) return null;
    const rows = tableData.outliers.map((sample) => ({ Sample: sample }));
    return `data:text/csv;charset=utf-8,${encodeURIComponent(rowsToCsv(rows, ["Sample"]))}`;
  }, [tableData]);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Data Completeness</h2>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700">Dataset level</label>
            <select
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
            </select>
          </div>
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

      {activeKindOptions.length > 0 && activeTab !== "tables" && advancedModeEnabled ? (
        <AdvancedPlotOptions
          key={activeTab}
          value={activeAdvancedSettings}
          onChange={(next) => setAdvancedByTab((prev) => ({ ...prev, [activeTab]: next }))}
          sampleOptions={sampleOptions}
          sampleDisplayLabels={activeSampleDisplayLabels}
          visibleControls={activeAdvancedVisibleControls}
          controlDefaults={activeAdvancedControlDefaults}
        />
      ) : null}

      {activeKindOptions.length > 0 && plotView ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">{plotView.title}</h3>
            <div className="flex flex-wrap items-center gap-2">
              <select
                value={downloadFormat}
                onChange={(e) => setDownloadFormat(e.target.value as PlotDownloadFormat)}
                className="rounded-xl border border-slate-300 bg-white px-2 py-2 text-sm text-slate-700 outline-none focus:border-slate-900"
              >
                {PLOT_DOWNLOAD_FORMAT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <a
                href={plotDownloadUrl}
                download={plotDownloadFilename}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download Plot
              </a>
            </div>
          </div>
          <div className="mt-4">
            <img
              key={plotView.url}
              src={plotView.url}
              alt={plotView.title}
              className="w-full rounded-xl border border-slate-200"
              onLoad={() => setImageError(null)}
              onError={() => setImageError("Failed to load plot image. Check backend logs for details.")}
            />
          </div>
          {imageError ? (
            <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {imageError}
            </div>
          ) : null}
        </section>
      ) : null}

      {activeKindOptions.length > 0 && activeTab === "tables" && isAnnotationKind(kind) ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">Missing Value Tables</h3>
            <button
              type="button"
              onClick={() => void loadTables()}
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

              <section>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <h4 className="text-base font-semibold text-slate-900">Sample-level Missing Values</h4>
                  {sampleCsvUrl ? (
                    <a
                      href={sampleCsvUrl}
                      download={`completeness_sample_summary_${kind}.csv`}
                      className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                    >
                      Download CSV
                    </a>
                  ) : null}
                </div>
                <PreviewTable rows={tableData.sampleSummary} emptyText="No sample summary rows available." />
              </section>

              <section>
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <h4 className="text-base font-semibold text-slate-900">Outliers by Missing Value %</h4>
                  {outlierCsvUrl ? (
                    <a
                      href={outlierCsvUrl}
                      download={`completeness_outliers_${kind}.csv`}
                      className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                    >
                      Download CSV
                    </a>
                  ) : null}
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
                  {featureCsvUrl ? (
                    <a
                      href={featureCsvUrl}
                      download={`completeness_feature_summary_${kind}.csv`}
                      className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                    >
                      Download CSV
                    </a>
                  ) : null}
                </div>
                <PreviewTable rows={tableData.featureSummary} emptyText="No feature summary rows available." />
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
        <OptionsLayout
          toggles={[
            <Checkbox key="header" label="Toggle Header" checked={missingPlot.header} onChange={(v) => setMissingPlot({ ...missingPlot, header: v })} />,
            <Checkbox key="text" label="Toggle Text" checked={missingPlot.text} onChange={(v) => setMissingPlot({ ...missingPlot, text: v })} />,
          ]}
          inputs={[
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
            <NumericField key="bin" label="Bin missing values" value={missingPlot.binCount} onChange={(v) => setMissingPlot({ ...missingPlot, binCount: Math.max(0, Math.round(v)) })} />,
            <NumericField key="text-size" label="Text Size" value={missingPlot.textSize} onChange={(v) => setMissingPlot({ ...missingPlot, textSize: Math.max(6, Math.min(24, Math.round(v))) })} />,
            <ColorField key="color" label="Bar Color" value={missingPlot.color} onChange={(value) => setMissingPlot({ ...missingPlot, color: value })} />,
          ]}
          sizeRow={
            <SizeRow
              dpi={missingPlot.dpi}
              heightCm={missingPlot.heightCm}
              widthCm={missingPlot.widthCm}
              onDpiChange={(v) => setMissingPlot({ ...missingPlot, dpi: Math.max(72, Math.round(v)) })}
              onHeightChange={(v) => setMissingPlot({ ...missingPlot, heightCm: Math.max(1, v) })}
              onWidthChange={(v) => setMissingPlot({ ...missingPlot, widthCm: Math.max(1, v) })}
            />
          }
        />
      );
    }

    if (activeTab === "heatmap") {
      return (
        <OptionsLayout
          toggles={[
            <Checkbox key="id" label="Toggle IDs" checked={heatmap.includeId} onChange={(v) => setHeatmap({ ...heatmap, includeId: v })} />,
            <Checkbox key="header" label="Toggle Header" checked={heatmap.header} onChange={(v) => setHeatmap({ ...heatmap, header: v })} />,
          ]}
          sizeRow={
            <SizeRow
              dpi={heatmap.dpi}
              heightCm={heatmap.heightCm}
              widthCm={heatmap.widthCm}
              onDpiChange={(v) => setHeatmap({ ...heatmap, dpi: Math.max(72, Math.round(v)) })}
              onHeightChange={(v) => setHeatmap({ ...heatmap, heightCm: Math.max(1, v) })}
              onWidthChange={(v) => setHeatmap({ ...heatmap, widthCm: Math.max(1, v) })}
            />
          }
        />
      );
    }

    return (
      <OptionsLayout
        toggles={[
          <Checkbox key="id" label="Toggle IDs" checked={tables.includeId} onChange={(v) => setTables({ ...tables, includeId: v })} />,
        ]}
        inputs={[
          <NumericField
            key="threshold"
            label="Outlier Threshold (%)"
            value={tables.outlierThreshold}
            onChange={(v) => setTables({ ...tables, outlierThreshold: Math.max(0, Math.min(100, v)) })}
          />,
        ]}
        sizeRow={<div />}
      />
    );
  }
}

function OptionsLayout({
  toggles,
  inputs,
  sizeRow,
}: {
  toggles: ReactNode[];
  inputs?: ReactNode[];
  sizeRow: ReactNode;
}) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3">{toggles}</div>
      {inputs && inputs.length > 0 ? <div className="grid gap-4 lg:grid-cols-3">{inputs}</div> : null}
      <div>{sizeRow}</div>
    </div>
  );
}

function ColorField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const fieldId = useId();
  return (
    <div>
      <label htmlFor={fieldId} className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input id={fieldId}
        type="color"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 w-full rounded-xl border border-slate-300 bg-white px-1 py-1"
      />
    </div>
  );
}

function PreviewTable({
  rows,
  emptyText,
}: {
  rows: Record<string, unknown>[];
  emptyText: string;
}) {
  const columns = useMemo(() => collectColumns(rows), [rows]);

  if (rows.length === 0 || columns.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        {emptyText}
      </div>
    );
  }

  return (
    <div className="max-h-[28rem] overflow-auto rounded-xl border border-slate-200">
      <table className="min-w-full table-fixed border-collapse text-sm">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((column) => (
              <th key={column} className="border-b border-slate-200 px-3 py-2 text-left font-medium text-slate-700">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="odd:bg-white even:bg-slate-50/50">
              {columns.map((column) => {
                const value = row[column];
                const text = value == null ? "" : String(value);
                return (
                  <td
                    key={`${rowIndex}-${column}`}
                    className="border-b border-slate-100 px-3 py-2 text-slate-600"
                    title={text}
                  >
                    <div className="max-w-[28ch] overflow-hidden text-ellipsis whitespace-nowrap">
                      {text}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
