import PlotImage from "../../components/PlotImage";
import PlotDownloadControls from "../../components/PlotDownloadControls";
import OptionsLayout from "../../components/OptionsLayout";
import { AssistantSelect } from "../../components/AssistantFields";
import { restorePlotDimensionCm, restorePlotDpi } from "../../lib/plotLimits";
import { SizeRow, MultiSelectField } from "../../components/PlotFields";
import CheckboxField from "../../components/CheckboxField";
import NumberField from "../../components/NumberField";
import { collectColumns } from "../../lib/tableData";
import { csvDataUrl, rowsToCsv } from "../../lib/tableData";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { buildPlotUrl, getSingleProteinOptions, getSingleProteinTable, isAbortError } from "../../lib/api";
import { useCurrentDatasetsSnapshot, useDatasetRevision } from "../../lib/datasetAvailability";
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
  SingleProteinIdentifier,
  SingleProteinOptionsResponse,
  SingleProteinTab,
  DataSource,
} from "../../lib/types";
import {
  dataSourceOptions,
} from "../../lib/types";
import { useDataSourceChoice } from "../../lib/useDataSourceChoice";
import PreviewTable from "../../components/PreviewTable";
import NotebookDownload, { type RenderedNotebook } from "../../components/NotebookDownload";
import SelectField from "../../components/SelectField";
import type { ContextMode } from "../../lib/types";
import LocalizationCutoffField from "../../components/LocalizationCutoffField";

type Props = {
  activeTab: SingleProteinTab;
  onContextModeChange?: (mode: ContextMode | null) => void;
  advancedPlotOptions?: ReactNode;
};

type PlotView = {
  title: string;
  url: string;
  filename: string;
} | null;

type TableRequest = {
  kind: AnnotationKind;
  tab: "boxplot" | "lineplot" | "heatmap";
  params: Record<string, string | number | boolean>;
};

export default function SingleProteinPage({ activeTab, onContextModeChange, advancedPlotOptions }: Props) {
  const advancedPlotSignal = useAdvancedPlotSignal();
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("single.protein.v1", {}),
    []
  );
  const persistedBox = (persisted.box as Record<string, unknown>) ?? {};
  const persistedLine = (persisted.line as Record<string, unknown>) ?? {};
  const persistedHeatmap = (persisted.heatmap as Record<string, unknown>) ?? {};
  const [kind, setKind] = useState<AnnotationKind>(() => {
    const value = String(persisted.kind ?? "protein").trim();
    return value === "protein" || value === "phospho" || value === "phosprot"
      ? value
      : "protein";
  });
  const { availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [options, setOptions] = useState<SingleProteinOptionsResponse | null>(null);
  const {
    dataSource,
    applyChoices: applyDataSourceChoices,
    chooseDataSource,
  } = useDataSourceChoice(persisted.dataSource);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [tableRows, setTableRows] = useState<Record<string, unknown>[]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);
  const [notebook, setNotebook] = useState<RenderedNotebook | null>(null);
  const [tableSnapshot, setTableSnapshot] = useState<string | null>(null);
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>(() =>
    coercePlotDownloadFormat(persisted.downloadFormat)
  );

  const [box, setBox] = useState({
    sampleN: Boolean(persistedBox.sampleN ?? true),
    identifier: (String(persistedBox.identifier ?? "workflow") === "genes" ? "genes" : "workflow") as SingleProteinIdentifier,
    protein: String(persistedBox.protein ?? ""),
    conditions: Array.isArray(persistedBox.conditions) ? persistedBox.conditions.map((value) => String(value ?? "")) : ([] as string[]),
    outliers: Boolean(persistedBox.outliers ?? false),
    dots: Boolean(persistedBox.dots ?? false),
    randomSeed: Number(persistedBox.randomSeed ?? 69),
    header: true,
    legend: true,
    widthCm: restorePlotDimensionCm(persistedBox.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedBox.heightCm, 10),
    dpi: restorePlotDpi(persistedBox.dpi, 300),
  });
  const [line, setLine] = useState({
    identifier: (String(persistedLine.identifier ?? "workflow") === "genes" ? "genes" : "workflow") as SingleProteinIdentifier,
    proteins: Array.isArray(persistedLine.proteins) ? persistedLine.proteins.map((value) => String(value ?? "")) : ([] as string[]),
    conditions: Array.isArray(persistedLine.conditions) ? persistedLine.conditions.map((value) => String(value ?? "")) : ([] as string[]),
    includeId: Boolean(persistedLine.includeId ?? false),
    showNaLow: Boolean(persistedLine.showNaLow ?? false),
    header: true,
    legend: true,
    widthCm: restorePlotDimensionCm(persistedLine.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedLine.heightCm, 10),
    dpi: restorePlotDpi(persistedLine.dpi, 300),
  });
  const [heatmap, setHeatmap] = useState({
    identifier: (String(persistedHeatmap.identifier ?? "workflow") === "genes" ? "genes" : "workflow") as SingleProteinIdentifier,
    protein: String(persistedHeatmap.protein ?? ""),
    conditions: Array.isArray(persistedHeatmap.conditions) ? persistedHeatmap.conditions.map((value) => String(value ?? "")) : ([] as string[]),
    includeId: Boolean(persistedHeatmap.includeId ?? false),
    header: true,
    filterM1: Boolean(persistedHeatmap.filterM1 ?? true),
    clusterRows: Boolean(persistedHeatmap.clusterRows ?? false),
    clusterCols: Boolean(persistedHeatmap.clusterCols ?? false),
    valueType: String(persistedHeatmap.valueType ?? "log2"),
    cmap: String(persistedHeatmap.cmap ?? "plasma"),
    widthCm: restorePlotDimensionCm(persistedHeatmap.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedHeatmap.heightCm, 12),
    dpi: restorePlotDpi(persistedHeatmap.dpi, 300),
  });

  useEffect(() => {
    writePersistedUiState("single.protein.v1", {
      kind,
      dataSource,
      downloadFormat,
      box,
      line,
      heatmap,
    });
  }, [kind, dataSource, downloadFormat, box, line, heatmap]);

  const effectiveKind: AnnotationKind = activeTab === "heatmap" ? "phospho" : kind;
  const activeIdentifier: SingleProteinIdentifier =
    activeTab === "boxplot" ? box.identifier : activeTab === "lineplot" ? line.identifier : heatmap.identifier;
  const hasPhospho = availableKinds.includes("phospho");
  const hasRequiredDataset = activeTab === "heatmap" ? hasPhospho : availableKinds.includes(effectiveKind);

  useEffect(() => {
    if (activeTab === "heatmap") return;
    if (availableKinds.length === 0) return;
    if (!availableKinds.includes(kind)) {
      setKind(availableKinds[0]);
    }
  }, [activeTab, availableKinds, kind]);

  useEffect(() => {
    if (!hasRequiredDataset) {
      setOptions(null);
      setOptionsLoading(false);
      setOptionsError(
        activeTab === "heatmap"
          ? "Upload a phospho dataset to use this tab."
          : "Upload a protein, phospho, or phosphoprotein dataset to use this tab."
      );
      return;
    }

    const controller = new AbortController();
    setOptions(null);
    setOptionsLoading(true);
    setOptionsError(null);
    getSingleProteinOptions(effectiveKind, activeTab, activeIdentifier, dataSource, { signal: controller.signal })
      .then((data) => {
        setOptions(data);
        // Unconditionally. This used to be gated on the response echoing back a
        // different source than the one requested -- but the request carries the
        // panel's current source, so the echo always matched and the ladder was
        // never applied. After the first apply the hook keeps a valid choice, so
        // running this every time changes nothing else.
        applyDataSourceChoices(data);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setOptions(null);
        setOptionsError(err instanceof Error ? err.message : "Failed to load options");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setOptionsLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [activeTab, effectiveKind, hasRequiredDataset, activeIdentifier, dataSource, applyDataSourceChoices]);

  useEffect(() => {
    if (!options) return;
    const proteinChoices = options.proteins ?? [];
    const conditionChoices = options.conditions ?? [];

    if (activeTab === "boxplot") {
      setBox((prev) => {
        const validIdentifiers = new Set((options.availableIdentifiers ?? []).map((entry) => entry.key));
        const nextIdentifier = validIdentifiers.has(prev.identifier)
          ? prev.identifier
          : (options.identifier ?? "workflow");
        const nextProtein =
          prev.protein && proteinChoices.includes(prev.protein) ? prev.protein : proteinChoices[0] ?? "";
        const filtered = prev.conditions.filter((value) => conditionChoices.includes(value));
        const nextConditions = filtered.length > 0 ? filtered : [...conditionChoices];
        return { ...prev, identifier: nextIdentifier, protein: nextProtein, conditions: nextConditions };
      });
      return;
    }

    if (activeTab === "lineplot") {
      setLine((prev) => {
        const validIdentifiers = new Set((options.availableIdentifiers ?? []).map((entry) => entry.key));
        const nextIdentifier = validIdentifiers.has(prev.identifier)
          ? prev.identifier
          : (options.identifier ?? "workflow");
        const filteredProteins = prev.proteins.filter((value) => proteinChoices.includes(value));
        const nextProteins =
          filteredProteins.length > 0 ? filteredProteins : proteinChoices.slice(0, Math.min(3, proteinChoices.length));
        const filteredConditions = prev.conditions.filter((value) => conditionChoices.includes(value));
        const nextConditions = filteredConditions.length > 0 ? filteredConditions : [...conditionChoices];
        return { ...prev, identifier: nextIdentifier, proteins: nextProteins, conditions: nextConditions };
      });
      return;
    }

    setHeatmap((prev) => {
      const validIdentifiers = new Set((options.availableIdentifiers ?? []).map((entry) => entry.key));
      const nextIdentifier = validIdentifiers.has(prev.identifier)
        ? prev.identifier
        : (options.identifier ?? "workflow");
      const nextProtein =
        prev.protein && proteinChoices.includes(prev.protein) ? prev.protein : proteinChoices[0] ?? "";
      const filtered = prev.conditions.filter((value) => conditionChoices.includes(value));
      const nextConditions = filtered.length > 0 ? filtered : [...conditionChoices];
      return { ...prev, identifier: nextIdentifier, protein: nextProtein, conditions: nextConditions };
    });
  }, [activeTab, options]);

  const plotView = useMemo<PlotView>(() => {
    void advancedPlotSignal;
    if (options?.dataSource !== dataSource) return null;
    if (activeTab === "boxplot") {
      if (!box.protein || box.conditions.length === 0) return null;
      return {
        title: "Protein Boxplot",
        filename: `single_protein_boxplot_${effectiveKind}.png`,
        url: buildPlotUrl(`/api/plots/single-protein/${effectiveKind}/boxplot.png`, {
          identifier: box.identifier,
          dataSource,
          protein: box.protein,
          conditions: JSON.stringify(box.conditions),
          outliers: box.outliers,
          dots: box.dots,
          sampleN: box.sampleN,
          randomSeed: box.randomSeed,
          header: box.header,
          legend: box.legend,
          widthCm: box.widthCm,
          heightCm: box.heightCm,
          dpi: box.dpi,
        }),
      };
    }

    if (activeTab === "lineplot") {
      if (line.proteins.length === 0 || line.conditions.length === 0) return null;
      return {
        title: "Protein Lineplot",
        filename: `single_protein_lineplot_${effectiveKind}.png`,
        url: buildPlotUrl(`/api/plots/single-protein/${effectiveKind}/lineplot.png`, {
          identifier: line.identifier,
          dataSource,
          proteins: JSON.stringify(line.proteins),
          conditions: JSON.stringify(line.conditions),
          includeId: line.includeId,
          showNaLow: line.showNaLow,
          header: line.header,
          legend: line.legend,
          widthCm: line.widthCm,
          heightCm: line.heightCm,
          dpi: line.dpi,
        }),
      };
    }

    if (!heatmap.protein || heatmap.conditions.length === 0) return null;
    return {
      title: "Phosphosites on Protein Heatmap",
      filename: "single_protein_heatmap_phospho.png",
      url: buildPlotUrl("/api/plots/single-protein/phospho/heatmap.png", {
        identifier: heatmap.identifier,
        dataSource,
        protein: heatmap.protein,
        conditions: JSON.stringify(heatmap.conditions),
        includeId: heatmap.includeId,
        header: heatmap.header,
        filterM1: heatmap.filterM1,
        clusterRows: heatmap.clusterRows,
        clusterCols: heatmap.clusterCols,
        valueType: heatmap.valueType,
        cmap: heatmap.cmap,
        widthCm: heatmap.widthCm,
        heightCm: heatmap.heightCm,
        dpi: heatmap.dpi,
      }),
    };
  }, [activeTab, box, line, heatmap, effectiveKind, dataSource, options?.dataSource, advancedPlotSignal]);
  const plotDownloadUrl = useMemo(() => {
    if (!plotView) return "";
    return withPlotDownloadFormat(plotView.url, downloadFormat);
  }, [plotView, downloadFormat]);
  const plotDownloadFilename = useMemo(() => {
    if (!plotView) return "";
    return withPlotDownloadFilename(plotView.filename, downloadFormat);
  }, [plotView, downloadFormat]);

  const plotToken = notebook?.url === plotView?.url ? notebook?.token : null;
  const tableRequest = useMemo<TableRequest | null>(() => {
    if (options?.dataSource !== dataSource) return null;
    if (activeTab === "boxplot") {
      if (!box.protein || box.conditions.length === 0) return null;
      const params: Record<string, string | number | boolean> = {
        identifier: box.identifier,
        dataSource,
        protein: box.protein,
        conditions: JSON.stringify(box.conditions),
      };
      return {
        kind: effectiveKind,
        tab: "boxplot" as const,
        params: plotToken ? { ...params, snapshot: plotToken } : params,
      };
    }

    if (activeTab === "lineplot") {
      if (line.proteins.length === 0 || line.conditions.length === 0) return null;
      const params: Record<string, string | number | boolean> = {
        identifier: line.identifier,
        dataSource,
        proteins: JSON.stringify(line.proteins),
        conditions: JSON.stringify(line.conditions),
        includeId: line.includeId,
      };
      return {
        kind: effectiveKind,
        tab: "lineplot" as const,
        params: plotToken ? { ...params, snapshot: plotToken } : params,
      };
    }

    if (!heatmap.protein || heatmap.conditions.length === 0) return null;
    const params: Record<string, string | number | boolean> = {
      identifier: heatmap.identifier,
      dataSource,
      protein: heatmap.protein,
      conditions: JSON.stringify(heatmap.conditions),
      includeId: heatmap.includeId,
      filterM1: heatmap.filterM1,
      clusterRows: heatmap.clusterRows,
      clusterCols: heatmap.clusterCols,
      valueType: heatmap.valueType,
    };
    return {
      kind: "phospho" as AnnotationKind,
      tab: "heatmap" as const,
      params: plotToken ? { ...params, snapshot: plotToken } : params,
    };
  }, [activeTab, effectiveKind, dataSource, options?.dataSource, plotToken,
    box.identifier, box.protein, box.conditions,
    line.identifier, line.proteins, line.conditions, line.includeId,
    heatmap.identifier, heatmap.protein, heatmap.conditions, heatmap.includeId,
    heatmap.filterM1, heatmap.clusterRows, heatmap.clusterCols, heatmap.valueType]);

  // The table depends on the data parameters, not on how the figure is drawn.
  // A new width, height or DPI draws a new figure under a new snapshot, but the
  // snapshot's table holds the same rows, so the rows already shown are kept and
  // only attributed to the new snapshot. A change to the dataset still reloads.
  const datasetRevision = useDatasetRevision();
  const loadedTableKey = useRef<string | null>(null);
  useEffect(() => {
    if (!tableRequest) {
      loadedTableKey.current = null;
      setTableRows([]);
      setTableLoading(false);
      setTableError(null);
      return;
    }
    const { snapshot, ...dataParams } = tableRequest.params;
    const snapshotToken = typeof snapshot === "string" ? snapshot : null;
    const dataKey = JSON.stringify([tableRequest.kind, tableRequest.tab, dataParams, datasetRevision]);
    if (loadedTableKey.current === dataKey) {
      if (snapshotToken) setTableSnapshot(snapshotToken);
      return;
    }
    loadedTableKey.current = null;
    const controller = new AbortController();
    setTableLoading(true);
    setTableError(null);
    getSingleProteinTable(tableRequest.kind, tableRequest.tab, tableRequest.params, { signal: controller.signal })
      .then((payload) => {
        if (controller.signal.aborted) return;
        loadedTableKey.current = dataKey;
        setTableRows(payload.rows ?? []);
        setTableSnapshot(snapshotToken);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setTableRows([]);
        setTableError(err instanceof Error ? err.message : "Failed to load table");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setTableLoading(false);
      });
    return () => {
      controller.abort();
    };
  }, [tableRequest, datasetRevision]);

  useEffect(() => {
    if (!onContextModeChange) return;
    if (activeTab !== "boxplot" && activeTab !== "lineplot" && activeTab !== "heatmap") {
      onContextModeChange(null);
      return;
    }
    const mode: ContextMode =
      activeTab === "boxplot"
        ? {
            kind: effectiveKind,
            dataSource: dataSource,
            tab: "boxplot",
            identifier: box.identifier,
            protein: box.protein,
            conditions: box.conditions,
            outliers: box.outliers,
            dots: box.dots,
            sampleN: box.sampleN,
            randomSeed: box.randomSeed,
            header: box.header,
            legend: box.legend,
          }
        : activeTab === "lineplot"
        ? {
            kind: effectiveKind,
            dataSource: dataSource,
            tab: "lineplot",
            identifier: line.identifier,
            proteins: line.proteins,
            conditions: line.conditions,
            includeId: line.includeId,
            showNaLow: line.showNaLow,
            header: line.header,
            legend: line.legend,
          }
        : {
            kind: "phospho",
            dataSource: dataSource,
            tab: "heatmap",
            identifier: heatmap.identifier,
            protein: heatmap.protein,
            conditions: heatmap.conditions,
            includeId: heatmap.includeId,
            header: heatmap.header,
            filterM1: heatmap.filterM1,
            clusterRows: heatmap.clusterRows,
            clusterCols: heatmap.clusterCols,
            valueType: heatmap.valueType,
          };
    onContextModeChange(mode);
  }, [
    onContextModeChange,
    activeTab,
    effectiveKind,
    dataSource,
    box.identifier,
    box.protein,
    box.conditions,
    box.outliers,
    box.dots,
    box.sampleN,
    box.randomSeed,
    box.header,
    box.legend,
    line.identifier,
    line.proteins,
    line.conditions,
    line.includeId,
    line.showNaLow,
    line.header,
    line.legend,
    heatmap.identifier,
    heatmap.protein,
    heatmap.conditions,
    heatmap.includeId,
    heatmap.header,
    heatmap.filterM1,
    heatmap.clusterRows,
    heatmap.clusterCols,
    heatmap.valueType,
  ]);

  const tableCsvUrl = useMemo(() => {
    if (tableRows.length === 0) return null;
    const columns = collectColumns(tableRows);
    if (columns.length === 0) return null;
    return csvDataUrl(rowsToCsv(tableRows, columns));
  }, [tableRows]);
  const tableWarnings = useMemo(
    () =>
      Array.from(
        new Set(
          tableRows
            .map((row) => String(row.Warning ?? "").trim())
            .filter((warning) => warning.length > 0)
        )
      ),
    [tableRows]
  );


  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Single Protein Pipeline</h2>
        <div className="mt-4 grid max-w-2xl gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-2 block font-medium text-slate-700">Dataset level</span>
            <AssistantSelect
              value={activeTab === "heatmap" ? (hasPhospho ? "phospho" : "") : kind}
              disabled={activeTab === "heatmap" || kindOptions.length === 0}
              onChange={(e) => setKind(e.target.value as AnnotationKind)}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:bg-slate-100 disabled:text-slate-500"
            >
              {activeTab === "heatmap" ? (
                hasPhospho ? (
                  <option value="phospho">Phospho</option>
                ) : (
                  <option value="">No phospho dataset available</option>
                )
              ) : kindOptions.length === 0 ? (
                <option value="">No dataset available</option>
              ) : (
                kindOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))
              )}
            </AssistantSelect>
            {activeTab === "heatmap" ? (
              <span className="mt-2 block text-xs text-slate-500">Heatmap uses phospho dataset level.</span>
            ) : null}
          </label>
          <LocalizationCutoffField kind={activeTab === "heatmap" ? "phospho" : kind} />
          <label className="block text-sm">
            <span className="mb-2 block font-medium text-slate-700">Data source</span>
            <AssistantSelect
              value={dataSource}
              onChange={(event) => chooseDataSource(event.target.value as DataSource)}
              disabled={!hasRequiredDataset || optionsLoading}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
            >
              {dataSourceOptions(options, dataSource).map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </AssistantSelect>
          </label>
        </div>
      </section>

      {!hasRequiredDataset ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
          {activeTab === "heatmap"
            ? "Upload a phospho dataset in the Data tab to render this heatmap."
            : "Upload a protein, phospho, or phosphoprotein dataset in the Data tab to render single-protein plots."}
        </section>
      ) : null}

      {hasRequiredDataset ? (
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
        {activeTab === "heatmap" && (heatmap.clusterRows || heatmap.clusterCols) && dataSource !== "imputed" ? (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Clustering uses only complete values. If this selected matrix contains missing values, choose successfully imputed data or disable clustering; values and data sources are never changed automatically.
          </div>
        ) : null}
      </section>
      ) : null}

      {hasRequiredDataset ? advancedPlotOptions : null}

      {hasRequiredDataset ? (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-900">{plotTitle(activeTab)}</h3>
          {plotView ? (
            <div className="flex flex-wrap items-center gap-2">
              <PlotDownloadControls label="Plot" format={downloadFormat} onFormatChange={setDownloadFormat}
                href={plotDownloadUrl} filename={plotDownloadFilename} />
              <NotebookDownload plotUrl={plotView.url} rendered={notebook} />
            </div>
          ) : null}
        </div>

        {plotView ? (
          <div className="mt-4">
            <PlotImage url={plotView.url} alt={plotView.title}
              onRendered={(url, token) => setNotebook({ url, token })} />
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
            Select required options to render the plot.
          </div>
        )}

        {!tableLoading && tableWarnings.length > 0 ? (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            {tableWarnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        ) : null}

      </section>
      ) : null}

      {hasRequiredDataset ? (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-900">Summary Table</h3>
          {tableCsvUrl ? (
            <div className="flex flex-wrap items-center gap-2">
              <a
                href={tableCsvUrl}
                download={`single_protein_${activeTab}_${effectiveKind}.csv`}
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
    const proteinOptions = options?.proteins ?? [];
    const conditionOptions = options?.conditions ?? [];
    const identifierEntries = options?.availableIdentifiers ?? [{ key: "workflow", label: "Workflow Names" }];
    const identifierOptions = identifierEntries.map((entry) => entry.key);
    const identifierLabels = Object.fromEntries(identifierEntries.map((entry) => [entry.key, entry.label]));

    if (activeTab === "boxplot") {
      return (
        <OptionsLayout columns={2}
          fields={[
            <SelectField
              key="identifier"
              label="Identifier"
              value={box.identifier}
              options={identifierOptions}
              labels={identifierLabels}
              onChange={(value) =>
                setBox({ ...box, identifier: value as SingleProteinIdentifier, protein: "" })
              }
            />,
            <SelectField
              key="protein"
              label={box.identifier === "genes" ? "Gene" : "Protein / Site"}
              value={box.protein}
              options={proteinOptions}
              onChange={(value) => setBox({ ...box, protein: value })}
            />,
            <MultiSelectField
              key="conditions"
              label="Conditions"
              value={box.conditions}
              options={conditionOptions}
              onChange={(value) => setBox({ ...box, conditions: value })}
            />,
            ...(box.dots
              ? [
                  <NumberField
                    key="randomSeed"
                    label="Random Seed"
                    value={box.randomSeed}
                    onChange={(value) =>
                      setBox({ ...box, randomSeed: Math.max(0, Math.round(value)) })
                    }
                  />,
                ]
              : []),
          ]}
          toggles={[
            <CheckboxField key="dots" label="Toggle Dots" checked={box.dots} onChange={(value) => setBox({ ...box, dots: value })} />,
            <CheckboxField key="sampleN" label="Toggle Sample n" checked={box.sampleN} onChange={(value) => setBox({ ...box, sampleN: value })} />,
            <CheckboxField key="outliers" label="Toggle Outliers" checked={box.outliers} onChange={(value) => setBox({ ...box, outliers: value })} />,
          ]}
          size={
            <SizeRow
              widthCm={box.widthCm}
              heightCm={box.heightCm}
              dpi={box.dpi}
              onWidthChange={(value) => setBox({ ...box, widthCm: value })}
              onHeightChange={(value) => setBox({ ...box, heightCm: value })}
              onDpiChange={(value) => setBox({ ...box, dpi: value })}
            />
          }
        />
      );
    }

    if (activeTab === "lineplot") {
      return (
        <OptionsLayout columns={2}
          fields={[
            <SelectField
              key="identifier"
              label="Identifier"
              value={line.identifier}
              options={identifierOptions}
              labels={identifierLabels}
              onChange={(value) =>
                setLine({ ...line, identifier: value as SingleProteinIdentifier, proteins: [] })
              }
            />,
            <MultiSelectField
              key="proteins"
              label={line.identifier === "genes" ? "Genes" : "Proteins / Sites"}
              value={line.proteins}
              options={proteinOptions}
              onChange={(value) => setLine({ ...line, proteins: value })}
            />,
            <MultiSelectField
              key="conditions"
              label="Conditions"
              value={line.conditions}
              options={conditionOptions}
              onChange={(value) => setLine({ ...line, conditions: value })}
            />,
          ]}
          toggles={[
            <CheckboxField key="id" label="Toggle ID" checked={line.includeId} onChange={(value) => setLine({ ...line, includeId: value })} />,
            <CheckboxField key="na-low" label="Show NA as low" checked={line.showNaLow} onChange={(value) => setLine({ ...line, showNaLow: value })} />,
          ]}
          size={
            <SizeRow
              widthCm={line.widthCm}
              heightCm={line.heightCm}
              dpi={line.dpi}
              onWidthChange={(value) => setLine({ ...line, widthCm: value })}
              onHeightChange={(value) => setLine({ ...line, heightCm: value })}
              onDpiChange={(value) => setLine({ ...line, dpi: value })}
            />
          }
        />
      );
    }

    return (
      <OptionsLayout columns={2}
        fields={[
          <SelectField
            key="identifier"
            label="Identifier"
            value={heatmap.identifier}
            options={identifierOptions}
            labels={identifierLabels}
            onChange={(value) =>
              setHeatmap({ ...heatmap, identifier: value as SingleProteinIdentifier, protein: "" })
            }
          />,
          <SelectField
            key="protein"
            label={heatmap.identifier === "genes" ? "Gene" : "Protein / Site"}
            value={heatmap.protein}
            options={proteinOptions}
            onChange={(value) => setHeatmap({ ...heatmap, protein: value })}
          />,
          <MultiSelectField
            key="conditions"
            label="Conditions"
            value={heatmap.conditions}
            options={conditionOptions}
            onChange={(value) => setHeatmap({ ...heatmap, conditions: value })}
          />,
          <SelectField
            key="valueType"
            label="Value Type"
            value={heatmap.valueType}
            options={["log2", "z"]}
            onChange={(value) => setHeatmap({ ...heatmap, valueType: value })}
          />,
          <SelectField
            key="cmap"
            label="Color Map"
            value={heatmap.cmap}
            options={["plasma", "viridis", "magma", "inferno", "coolwarm"]}
            onChange={(value) => setHeatmap({ ...heatmap, cmap: value })}
          />,
        ]}
        toggles={[
          <CheckboxField key="id" label="Toggle ID" checked={heatmap.includeId} onChange={(value) => setHeatmap({ ...heatmap, includeId: value })} />,
          <CheckboxField key="filter" label="Filter *_M1" checked={heatmap.filterM1} onChange={(value) => setHeatmap({ ...heatmap, filterM1: value })} />,
          <CheckboxField key="rows" label="Cluster Rows" checked={heatmap.clusterRows} onChange={(value) => setHeatmap({ ...heatmap, clusterRows: value })} />,
          <CheckboxField key="cols" label="Cluster Columns" checked={heatmap.clusterCols} onChange={(value) => setHeatmap({ ...heatmap, clusterCols: value })} />,
        ]}
        size={
          <SizeRow
            widthCm={heatmap.widthCm}
            heightCm={heatmap.heightCm}
            dpi={heatmap.dpi}
            onWidthChange={(value) => setHeatmap({ ...heatmap, widthCm: value })}
            onHeightChange={(value) => setHeatmap({ ...heatmap, heightCm: value })}
            onDpiChange={(value) => setHeatmap({ ...heatmap, dpi: value })}
          />
        }
      />
    );
  }
}

function plotTitle(tab: SingleProteinTab): string {
  if (tab === "boxplot") return "Protein Boxplot";
  if (tab === "lineplot") return "Protein Lineplot";
  return "Phosphosites on Protein Heatmap";
}
