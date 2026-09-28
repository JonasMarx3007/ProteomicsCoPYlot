import PlotImage from "../../components/PlotImage";
import { AssistantSelect } from "../../components/AssistantFields";
import { restorePlotDimensionCm, restorePlotDpi } from "../../lib/plotLimits";
import { SizeRow, MultiSelectField, NumericField, Checkbox } from "../../components/PlotFields";
import { collectColumns } from "../../lib/tableData";
import { rowsToCsv } from "../../lib/tableData";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { TEST_TYPE_VALUES, TEST_TYPE_LABELS } from "../../lib/statisticalTests";
import { buildPlotUrl, getPhosphoOptions, getPhosphoTable, isAbortError, pairingIsReady } from "../../lib/api";
import PairingEditor from "../../components/PairingEditor";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import {
  PLOT_DOWNLOAD_FORMAT_OPTIONS,
  coercePlotDownloadFormat,
  type PlotDownloadFormat,
  withPlotDownloadFilename,
  withPlotDownloadFormat,
} from "../../lib/plotDownload";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import { useDataSourceChoice } from "../../lib/useDataSourceChoice";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import { useAdvancedPlotSignal } from "../../lib/useAdvancedPlotSignal";
import { dataSourceOptions, type DataSource, type PhosphoOptionsResponse, type PhosphoTab } from "../../lib/types";
import PreviewTable from "../../components/PaginatedTable";
import SelectField from "../../components/SelectField";
import type { ContextMode } from "../../lib/types";

type Props = {
  activeTab: PhosphoTab;
  onContextModeChange?: (mode: ContextMode | null) => void;
  advancedPlotOptions?: ReactNode;
};

type PlotView = {
  title: string;
  url: string;
  filename: string;
  type: "image" | "html";
} | null;

type TableRequest = {
  tab: PhosphoTab;
  params?: Record<string, string | number | boolean>;
} | null;

export default function PhosphoSpecificPage({ activeTab, onContextModeChange, advancedPlotOptions }: Props) {
  const advancedPlotSignal = useAdvancedPlotSignal();
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("phospho.specific.v1", {}),
    []
  );
  const persistedPhosphositePlot = (persisted.phosphositePlot as Record<string, unknown>) ?? {};
  const persistedCoverage = (persisted.coverage as Record<string, unknown>) ?? {};
  const persistedDistribution = (persisted.distribution as Record<string, unknown>) ?? {};
  const persistedSty = (persisted.sty as Record<string, unknown>) ?? {};
  const persistedPhosprotRegulation = (persisted.phosprotRegulation as Record<string, unknown>) ?? {};
  const { datasets } = useCurrentDatasetsSnapshot();
  const hasPhosphoDataset = Boolean(datasets?.phospho);
  const [options, setOptions] = useState<PhosphoOptionsResponse | null>(null);
  // The data source for Phosprot Regulation: the same choice the phospho
  // volcano offers, so the sites it sums are the sites that volcano shows.
  const {
    dataSource,
    applyChoices: applyDataSourceChoices,
    chooseDataSource,
  } = useDataSourceChoice(persisted.dataSource);
  const volcanoDataSourceOptions = useMemo(() => dataSourceOptions(options), [options]);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [tableRows, setTableRows] = useState<Record<string, unknown>[]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>(() =>
    coercePlotDownloadFormat(persisted.downloadFormat)
  );

  const [phosphositePlot, setPhosphositePlot] = useState({
    cutoff: Number(persistedPhosphositePlot.cutoff ?? 0),
    color: String(persistedPhosphositePlot.color ?? "#87CEEB"),
    widthCm: restorePlotDimensionCm(persistedPhosphositePlot.widthCm, 15),
    heightCm: restorePlotDimensionCm(persistedPhosphositePlot.heightCm, 10),
    dpi: restorePlotDpi(persistedPhosphositePlot.dpi, 100),
  });

  const [coverage, setCoverage] = useState({
    includeId: Boolean(persistedCoverage.includeId ?? false),
    header: true,
    legend: true,
    mode: String(persistedCoverage.mode ?? "Normal"),
    colorClassI: String(persistedCoverage.colorClassI ?? "#2563eb"),
    colorNotClassI: String(persistedCoverage.colorNotClassI ?? "#f59e0b"),
    randomSeed: Number(persistedCoverage.randomSeed ?? 69),
    conditions: Array.isArray(persistedCoverage.conditions)
      ? persistedCoverage.conditions.map((value) => String(value ?? ""))
      : ([] as string[]),
    widthCm: restorePlotDimensionCm(persistedCoverage.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedCoverage.heightCm, 10),
    dpi: restorePlotDpi(persistedCoverage.dpi, 300),
  });

  const [distribution, setDistribution] = useState({
    cutoff: Number(persistedDistribution.cutoff ?? 0),
    header: true,
    color: String(persistedDistribution.color ?? "#87CEEB"),
    widthCm: restorePlotDimensionCm(persistedDistribution.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedDistribution.heightCm, 15),
    dpi: restorePlotDpi(persistedDistribution.dpi, 300),
  });

  const [sty, setSty] = useState({
    header: true,
    widthCm: restorePlotDimensionCm(persistedSty.widthCm, 17.78),
    heightCm: restorePlotDimensionCm(persistedSty.heightCm, 11.43),
    dpi: restorePlotDpi(persistedSty.dpi, 140),
  });


  const [phosprotRegulation, setPhosprotRegulation] = useState({
    condition1: String(persistedPhosprotRegulation.condition1 ?? ""),
    condition2: String(persistedPhosprotRegulation.condition2 ?? ""),
    pValueThreshold: Number(persistedPhosprotRegulation.pValueThreshold ?? 0.05),
    log2fcThreshold: Number(persistedPhosprotRegulation.log2fcThreshold ?? 1),
    testType: String(persistedPhosprotRegulation.testType ?? "unpaired"),
    useUncorrected: Boolean(persistedPhosprotRegulation.useUncorrected ?? false),
    maxHoverSites: Number(persistedPhosprotRegulation.maxHoverSites ?? 20),
    showPhosphosites: Boolean(persistedPhosprotRegulation.showPhosphosites ?? true),
    header: true,
    widthCm: restorePlotDimensionCm(persistedPhosprotRegulation.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedPhosprotRegulation.heightCm, 12),
    dpi: restorePlotDpi(persistedPhosprotRegulation.dpi, 220),
  });
  const debouncedPhosphositePlot = useDebouncedValue(phosphositePlot, 650);
  const debouncedCoverage = useDebouncedValue(coverage, 650);
  const debouncedDistribution = useDebouncedValue(distribution, 650);
  const debouncedSty = useDebouncedValue(sty, 650);
  const debouncedDataSource = useDebouncedValue(dataSource, 650);
  const debouncedPhosprotRegulation = useDebouncedValue(phosprotRegulation, 650);
  const phosprotPairingReady =
    debouncedPhosprotRegulation.testType !== "paired" ||
    pairingIsReady(
      debouncedPhosprotRegulation.condition1,
      debouncedPhosprotRegulation.condition2,
      options?.samplesByCondition ?? {},
      options?.pairIdsBySample ?? {}
    );

  useEffect(() => {
    writePersistedUiState("phospho.specific.v1", {
      downloadFormat,
      dataSource,
      phosphositePlot,
      coverage,
      distribution,
      sty,
      phosprotRegulation,
    });
  }, [downloadFormat, dataSource, phosphositePlot, coverage, distribution, sty, phosprotRegulation]);

  useEffect(() => {
    if (!hasPhosphoDataset) {
      setOptions(null);
      setOptionsLoading(false);
      setOptionsError("No phospho dataset loaded.");
      return;
    }
    const controller = new AbortController();
    setOptionsLoading(true);
    setOptionsError(null);
    getPhosphoOptions({ signal: controller.signal })
      .then((data) => {
        setOptions(data);
        applyDataSourceChoices(data);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setOptions(null);
        setOptionsError(err instanceof Error ? err.message : "Failed to load phospho options");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setOptionsLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [hasPhosphoDataset, applyDataSourceChoices]);

  useEffect(() => {
    const conditionOptions = options?.conditions ?? [];
    setCoverage((prev) => {
      const filtered = prev.conditions.filter((value) => conditionOptions.includes(value));
      const nextConditions = filtered.length > 0 ? filtered : [...conditionOptions];
      return { ...prev, conditions: nextConditions };
    });
  }, [options]);

  useEffect(() => {
    const conditionOptions = options?.conditions ?? [];
    if (conditionOptions.length < 2) {
      return;
    }
    setPhosprotRegulation((prev) => {
      const nextCondition1 = conditionOptions.includes(prev.condition1) ? prev.condition1 : conditionOptions[0];
      const nextCondition2 = conditionOptions.includes(prev.condition2)
        ? prev.condition2
        : nextCondition1;
      return { ...prev, condition1: nextCondition1, condition2: nextCondition2 };
    });
  }, [options]);

  const phosprotSelectionInvalid =
    activeTab === "phosprotRegulation" &&
    phosprotRegulation.condition1.trim() !== "" &&
    phosprotRegulation.condition1 === phosprotRegulation.condition2;

  const plotView = useMemo<PlotView>(() => {
    void advancedPlotSignal;
    if (activeTab === "phosphositePlot") {
      return {
        title: "Phosphosite Plot",
        filename: "phosphosite_plot.png",
        type: "image",
        url: buildPlotUrl("/api/plots/phospho/phosphosite-plot.png", {
          cutoff: debouncedPhosphositePlot.cutoff,
          color: debouncedPhosphositePlot.color,
          widthCm: debouncedPhosphositePlot.widthCm,
          heightCm: debouncedPhosphositePlot.heightCm,
          dpi: debouncedPhosphositePlot.dpi,
        }),
      };
    }

    if (activeTab === "coverage") {
      return {
        title: "Phosphosite Coverage Plot",
        filename: "phosphosite_coverage_plot.png",
        type: "image",
        url: buildPlotUrl("/api/plots/phospho/coverage.png", {
          includeId: debouncedCoverage.includeId,
          header: debouncedCoverage.header,
          legend: debouncedCoverage.legend,
          mode: debouncedCoverage.mode,
          colorClassI: debouncedCoverage.colorClassI,
          colorNotClassI: debouncedCoverage.colorNotClassI,
          randomSeed: debouncedCoverage.randomSeed,
          widthCm: debouncedCoverage.widthCm,
          heightCm: debouncedCoverage.heightCm,
          dpi: debouncedCoverage.dpi,
          conditions: JSON.stringify(debouncedCoverage.conditions),
        }),
      };
    }

    if (activeTab === "distribution") {
      return {
        title: "Phosphosite Distribution",
        filename: "phosphosite_distribution.png",
        type: "image",
        url: buildPlotUrl("/api/plots/phospho/distribution.png", {
          cutoff: debouncedDistribution.cutoff,
          header: debouncedDistribution.header,
          color: debouncedDistribution.color,
          widthCm: debouncedDistribution.widthCm,
          heightCm: debouncedDistribution.heightCm,
          dpi: debouncedDistribution.dpi,
        }),
      };
    }

    if (activeTab === "phosprotRegulation") {
      if (!debouncedPhosprotRegulation.condition1 || !debouncedPhosprotRegulation.condition2) return null;
      if (debouncedPhosprotRegulation.condition1 === debouncedPhosprotRegulation.condition2) return null;
      if (!phosprotPairingReady) return null;
      return {
        title: "Phosprot Regulation",
        filename: "phosprot_regulation.html",
        type: "html",
        url: buildPlotUrl("/api/plots/phospho/phosprot-regulation.html", {
          dataSource: debouncedDataSource,
          condition1: debouncedPhosprotRegulation.condition1,
          condition2: debouncedPhosprotRegulation.condition2,
          pValueThreshold: debouncedPhosprotRegulation.pValueThreshold,
          log2fcThreshold: debouncedPhosprotRegulation.log2fcThreshold,
          testType: debouncedPhosprotRegulation.testType,
          useUncorrected: debouncedPhosprotRegulation.useUncorrected,
          maxHoverSites: debouncedPhosprotRegulation.maxHoverSites,
          showPhosphosites: debouncedPhosprotRegulation.showPhosphosites,
          header: debouncedPhosprotRegulation.header,
          widthCm: debouncedPhosprotRegulation.widthCm,
          heightCm: debouncedPhosprotRegulation.heightCm,
          dpi: debouncedPhosprotRegulation.dpi,
        }),
      };
    }

    return {
      title: "STY Plot",
      filename: "sty_plot.png",
      type: "image",
      url: buildPlotUrl("/api/plots/phospho/sty.png", {
        header: debouncedSty.header,
        widthCm: debouncedSty.widthCm,
        heightCm: debouncedSty.heightCm,
        dpi: debouncedSty.dpi,
      }),
    };
  }, [
    activeTab,
    debouncedPhosphositePlot,
    debouncedCoverage,
    debouncedDistribution,
    debouncedSty,
    debouncedDataSource,
    debouncedPhosprotRegulation,
    phosprotPairingReady,
    advancedPlotSignal,
  ]);
  const plotDownloadUrl = useMemo(() => {
    if (!plotView || plotView.type !== "image") return "";
    return withPlotDownloadFormat(plotView.url, downloadFormat);
  }, [plotView, downloadFormat]);
  const plotDownloadFilename = useMemo(() => {
    if (!plotView || plotView.type !== "image") return "";
    return withPlotDownloadFilename(plotView.filename, downloadFormat);
  }, [plotView, downloadFormat]);

  const tableRequest = useMemo<TableRequest>(() => {
    if (activeTab === "phosphositePlot") {
      const params: Record<string, string | number | boolean> = {
        cutoff: debouncedPhosphositePlot.cutoff,
      };
      return {
        tab: "phosphositePlot",
        params,
      };
    }

    if (activeTab === "coverage") {
      const params: Record<string, string | number | boolean> = {
        includeId: debouncedCoverage.includeId,
        mode: debouncedCoverage.mode,
        conditions: JSON.stringify(debouncedCoverage.conditions),
      };
      return {
        tab: "coverage",
        params,
      };
    }

    if (activeTab === "distribution") {
      const params: Record<string, string | number | boolean> = {
        cutoff: debouncedDistribution.cutoff,
      };
      return {
        tab: "distribution",
        params,
      };
    }

    if (activeTab === "phosprotRegulation") {
      if (!debouncedPhosprotRegulation.condition1 || !debouncedPhosprotRegulation.condition2) return null;
      if (debouncedPhosprotRegulation.condition1 === debouncedPhosprotRegulation.condition2) return null;
      if (!phosprotPairingReady) return null;
      const params: Record<string, string | number | boolean> = {
        dataSource: debouncedDataSource,
        condition1: debouncedPhosprotRegulation.condition1,
        condition2: debouncedPhosprotRegulation.condition2,
        pValueThreshold: debouncedPhosprotRegulation.pValueThreshold,
        log2fcThreshold: debouncedPhosprotRegulation.log2fcThreshold,
        testType: debouncedPhosprotRegulation.testType,
        useUncorrected: debouncedPhosprotRegulation.useUncorrected,
        maxHoverSites: debouncedPhosprotRegulation.maxHoverSites,
        showPhosphosites: debouncedPhosprotRegulation.showPhosphosites,
      };
      return {
        tab: "phosprotRegulation",
        params,
      };
    }

    return { tab: "sty" };
  }, [
    activeTab,
    debouncedPhosphositePlot.cutoff,
    debouncedCoverage.includeId,
    debouncedCoverage.mode,
    debouncedCoverage.conditions,
    debouncedDistribution.cutoff,
    debouncedDataSource,
    debouncedPhosprotRegulation,
    phosprotPairingReady,
  ]);

  useEffect(() => {
    if (!hasPhosphoDataset) {
      setTableRows([]);
      setTableLoading(false);
      setTableError("No phospho dataset loaded.");
      return;
    }
    if (!tableRequest) {
      setTableRows([]);
      setTableLoading(false);
      setTableError(null);
      return;
    }

    const controller = new AbortController();
    setTableLoading(true);
    setTableError(null);
    getPhosphoTable(tableRequest.tab, tableRequest.params, { signal: controller.signal })
      .then((payload) => {
        setTableRows(payload.rows ?? []);
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setTableRows([]);
        setTableError(err instanceof Error ? err.message : "Failed to load phospho table");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setTableLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [tableRequest, hasPhosphoDataset]);

  useEffect(() => {
    if (!onContextModeChange) return;
    if (
      !hasPhosphoDataset ||
      (
        activeTab !== "phosphositePlot" &&
        activeTab !== "coverage" &&
        activeTab !== "distribution" &&
        activeTab !== "sty" &&
        activeTab !== "phosprotRegulation"
      )
    ) {
      onContextModeChange(null);
      return;
    }
    const mode: ContextMode =
      activeTab === "phosphositePlot"
        ? {
            tab: "phosphositePlot",
            cutoff: debouncedPhosphositePlot.cutoff,
          }
        : activeTab === "distribution"
        ? {
            tab: "distribution",
            cutoff: debouncedDistribution.cutoff,
          }
        : activeTab === "sty"
        ? { tab: "sty" }
        : activeTab === "phosprotRegulation"
        ? {
            tab: "phosprotRegulation",
            dataSource: debouncedDataSource,
            condition1: debouncedPhosprotRegulation.condition1,
            condition2: debouncedPhosprotRegulation.condition2,
            pValueThreshold: debouncedPhosprotRegulation.pValueThreshold,
            log2fcThreshold: debouncedPhosprotRegulation.log2fcThreshold,
            testType: debouncedPhosprotRegulation.testType,
            useUncorrected: debouncedPhosprotRegulation.useUncorrected,
            maxHoverSites: debouncedPhosprotRegulation.maxHoverSites,
            showPhosphosites: debouncedPhosprotRegulation.showPhosphosites,
          }
        : {
            tab: "coverage",
            mode: coverage.mode,
            includeId: coverage.includeId,
            randomSeed: coverage.randomSeed,
            conditions: coverage.conditions,
          };
    onContextModeChange(mode);
  }, [
    onContextModeChange,
    hasPhosphoDataset,
    activeTab,
    debouncedPhosphositePlot.cutoff,
    debouncedDistribution.cutoff,
    debouncedDataSource,
    debouncedPhosprotRegulation.condition1,
    debouncedPhosprotRegulation.condition2,
    debouncedPhosprotRegulation.pValueThreshold,
    debouncedPhosprotRegulation.log2fcThreshold,
    debouncedPhosprotRegulation.testType,
    debouncedPhosprotRegulation.useUncorrected,
    debouncedPhosprotRegulation.maxHoverSites,
    debouncedPhosprotRegulation.showPhosphosites,
    coverage.mode,
    coverage.includeId,
    coverage.randomSeed,
    coverage.conditions,
  ]);

  const tableCsvUrl = useMemo(() => {
    if (tableRows.length === 0) return null;
    const columns = collectColumns(tableRows);
    if (columns.length === 0) return null;
    return `data:text/csv;charset=utf-8,${encodeURIComponent(rowsToCsv(tableRows, columns))}`;
  }, [tableRows]);


  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Options</h3>
        {!hasPhosphoDataset ? (
          <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50 px-4 py-6 text-sm text-sky-800">
            Upload a phospho dataset in the Data tab to configure phospho-specific options.
          </div>
        ) : optionsLoading ? (
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

      {advancedPlotOptions}

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-900">{plotTitle(activeTab)}</h3>
          {hasPhosphoDataset && plotView && plotView.type === "image" ? (
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
          ) : hasPhosphoDataset && plotView ? (
            <a
              href={plotView.url}
              target="_blank"
              rel="noreferrer"
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
            >
              Open Plot
            </a>
          ) : null}
        </div>

        {!hasPhosphoDataset ? (
          <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50 px-4 py-6 text-sm text-sky-800">
            No phospho dataset loaded. Plot preview is unavailable.
          </div>
        ) : phosprotSelectionInvalid ? (
          <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50 px-4 py-6 text-sm text-sky-800">
            Please select two different conditions to generate the plot.
          </div>
        ) : plotView ? (
          <div className="mt-4">
            {plotView.type === "html" ? (
              <iframe
                sandbox="allow-scripts allow-downloads"
                key={plotView.url}
                src={plotView.url}
                title={plotView.title}
                className="h-[40rem] w-full rounded-xl border border-slate-200"
              />
            ) : (
              <PlotImage url={plotView.url} alt={plotView.title} />
            )}
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
            Select required options to render the plot.
          </div>
        )}

      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-900">Summary Table</h3>
          {hasPhosphoDataset && tableCsvUrl ? (
            <a
              href={tableCsvUrl}
              download={`phospho_${activeTab}.csv`}
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
            >
              Download CSV
            </a>
          ) : null}
        </div>
        <div className="mt-4">
          {!hasPhosphoDataset ? (
            <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-6 text-sm text-sky-800">
              No phospho dataset loaded. Summary table is unavailable.
            </div>
          ) : phosprotSelectionInvalid ? (
            <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-6 text-sm text-sky-800">
              Please select two different conditions to generate the table.
            </div>
          ) : tableLoading ? (
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
    </div>
  );

  function renderOptions() {
    const conditionOptions = options?.conditions ?? [];

    if (activeTab === "phosphositePlot") {
      return (
        <OptionsLayout
          fields={[
            <NumericField
              key="cutoff"
              label="Cutoff"
              value={phosphositePlot.cutoff}
              onChange={(value) => setPhosphositePlot({ ...phosphositePlot, cutoff: Math.max(0, value) })}
            />,
          ]}
          sizeRow={
            <SizeRow
              widthCm={phosphositePlot.widthCm}
              heightCm={phosphositePlot.heightCm}
              dpi={phosphositePlot.dpi}
              onWidthChange={(value) => setPhosphositePlot({ ...phosphositePlot, widthCm: value })}
              onHeightChange={(value) => setPhosphositePlot({ ...phosphositePlot, heightCm: value })}
              onDpiChange={(value) => setPhosphositePlot({ ...phosphositePlot, dpi: value })}
            />
          }
        />
      );
    }

    if (activeTab === "coverage") {
      return (
        <OptionsLayout
          fields={[
            <SelectField
              key="mode"
              label="Type"
              value={coverage.mode}
              options={["Normal", "Summary"]}
              onChange={(value) => setCoverage({ ...coverage, mode: value })}
            />,
            <MultiSelectField
              key="conditions"
              label="Conditions"
              value={coverage.conditions}
              options={conditionOptions}
              onChange={(value) => setCoverage({ ...coverage, conditions: value })}
            />,
            ...(coverage.mode === "Summary"
              ? [
                  <NumericField
                    key="randomSeed"
                    label="Random Seed"
                    value={coverage.randomSeed}
                    onChange={(value) =>
                      setCoverage({ ...coverage, randomSeed: Math.max(0, Math.round(value)) })
                    }
                  />,
                ]
              : []),
          ]}
          toggles={[
            <Checkbox key="id" label="Toggle ID" checked={coverage.includeId} onChange={(value) => setCoverage({ ...coverage, includeId: value })} />,
          ]}
          sizeRow={
            <SizeRow
              widthCm={coverage.widthCm}
              heightCm={coverage.heightCm}
              dpi={coverage.dpi}
              onWidthChange={(value) => setCoverage({ ...coverage, widthCm: value })}
              onHeightChange={(value) => setCoverage({ ...coverage, heightCm: value })}
              onDpiChange={(value) => setCoverage({ ...coverage, dpi: value })}
            />
          }
        />
      );
    }

    if (activeTab === "distribution") {
      return (
        <OptionsLayout
          fields={[
            <NumericField
              key="cutoff"
              label="Cutoff"
              value={distribution.cutoff}
              onChange={(value) => setDistribution({ ...distribution, cutoff: Math.max(0, Math.min(1, value)) })}
            />,
          ]}
          toggles={[
          ]}
          sizeRow={
            <SizeRow
              widthCm={distribution.widthCm}
              heightCm={distribution.heightCm}
              dpi={distribution.dpi}
              onWidthChange={(value) => setDistribution({ ...distribution, widthCm: value })}
              onHeightChange={(value) => setDistribution({ ...distribution, heightCm: value })}
              onDpiChange={(value) => setDistribution({ ...distribution, dpi: value })}
            />
          }
        />
      );
    }

    if (activeTab === "phosprotRegulation") {
      return (
        <OptionsLayout
          fields={[
            <SelectField
              key="dataSource"
              label="Data Source"
              value={dataSource}
              options={volcanoDataSourceOptions.map((option) => option.value)}
              labels={Object.fromEntries(volcanoDataSourceOptions.map((option) => [option.value, option.label]))}
              onChange={(value) => chooseDataSource(value as DataSource)}
            />,
            <SelectField
              key="condition1"
              label="Condition 1"
              value={phosprotRegulation.condition1}
              options={conditionOptions}
              onChange={(value) => {
                const keep = conditionOptions.includes(phosprotRegulation.condition2)
                  ? phosprotRegulation.condition2
                  : value;
                setPhosprotRegulation({
                  ...phosprotRegulation,
                  condition1: value,
                  condition2: keep,
                });
              }}
            />,
            <SelectField
              key="condition2"
              label="Condition 2"
              value={phosprotRegulation.condition2}
              options={conditionOptions}
              onChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, condition2: value })}
            />,
            <NumericField
              key="pValueThreshold"
              label="P-value Threshold"
              value={phosprotRegulation.pValueThreshold}
              onChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, pValueThreshold: Math.max(1e-12, Math.min(1, value)) })}
            />,
            <NumericField
              key="log2fcThreshold"
              label="log2 FC Threshold"
              value={phosprotRegulation.log2fcThreshold}
              onChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, log2fcThreshold: Math.max(0, value) })}
            />,
            <SelectField
              key="testType"
              label="Test Type"
              value={phosprotRegulation.testType}
              options={TEST_TYPE_VALUES}
              labels={TEST_TYPE_LABELS}
              onChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, testType: value })}
            />,
            ...(phosprotRegulation.testType === "paired"
              ? [
                  <div key="pairing" className="lg:col-span-2">
                    <PairingEditor
                      kind="phospho"
                      condition1={phosprotRegulation.condition1}
                      condition2={phosprotRegulation.condition2}
                      samplesByCondition={options?.samplesByCondition ?? {}}
                      pairIdsBySample={options?.pairIdsBySample ?? {}}
                      onSaved={async () => setOptions(await getPhosphoOptions())}
                    />
                  </div>,
                ]
              : []),
            <NumericField
              key="maxHoverSites"
              label="Max Sites in Table"
              value={phosprotRegulation.maxHoverSites}
              onChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, maxHoverSites: Math.max(1, Math.round(value)) })}
            />,
          ]}
          toggles={[
            <Checkbox key="uncorrected" label="Use Uncorrected P-values" checked={phosprotRegulation.useUncorrected} onChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, useUncorrected: value })} />,
            <Checkbox key="showSites" label="Show Phosphosites in Table" checked={phosprotRegulation.showPhosphosites} onChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, showPhosphosites: value })} />,
          ]}
          sizeRow={
            <SizeRow
              widthCm={phosprotRegulation.widthCm}
              heightCm={phosprotRegulation.heightCm}
              dpi={phosprotRegulation.dpi}
              onWidthChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, widthCm: value })}
              onHeightChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, heightCm: value })}
              onDpiChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, dpi: value })}
            />
          }
        />
      );
    }

    return (
      <OptionsLayout
        fields={[]}
        toggles={[
        ]}
        sizeRow={
          <SizeRow
            widthCm={sty.widthCm}
            heightCm={sty.heightCm}
            dpi={sty.dpi}
            onWidthChange={(value) => setSty({ ...sty, widthCm: value })}
            onHeightChange={(value) => setSty({ ...sty, heightCm: value })}
            onDpiChange={(value) => setSty({ ...sty, dpi: value })}
          />
        }
      />
    );
  }
}

function plotTitle(tab: PhosphoTab): string {
  if (tab === "phosphositePlot") return "Phosphosite Plot";
  if (tab === "coverage") return "Phosphosite Coverage Plot";
  if (tab === "distribution") return "Phosphosite Distribution";
  if (tab === "phosprotRegulation") return "Phosprot Regulation";
  return "STY Plot";
}

function OptionsLayout({
  fields,
  toggles,
  sizeRow,
}: {
  fields: ReactNode[];
  toggles?: ReactNode[];
  sizeRow: ReactNode;
}) {
  return (
    <div className="space-y-4">
      {fields.length > 0 ? <div className="grid gap-4 lg:grid-cols-2">{fields}</div> : null}
      {toggles && toggles.length > 0 ? <div className="flex flex-wrap gap-3">{toggles}</div> : null}
      <div>{sizeRow}</div>
    </div>
  );
}
