import { useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, getPhosphoOptions, getPhosphoTable } from "../../lib/api";
import PaginatedTable from "../../components/PaginatedTable";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import {
  PLOT_DOWNLOAD_FORMAT_OPTIONS,
  type PlotDownloadFormat,
  withPlotDownloadFilename,
  withPlotDownloadFormat,
} from "../../lib/plotDownload";
import { useDebouncedValue } from "../../lib/useDebouncedValue";
import type { PhosphoOptionsResponse, PhosphoTab } from "../../lib/types";

type Props = {
  activeTab: PhosphoTab;
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

export default function PhosphoSpecificPage({ activeTab }: Props) {
  const { datasets } = useCurrentDatasetsSnapshot();
  const hasPhosphoDataset = Boolean(datasets?.phospho);
  const [options, setOptions] = useState<PhosphoOptionsResponse | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [tableRows, setTableRows] = useState<Record<string, unknown>[]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>("png");

  const [phosphositePlot, setPhosphositePlot] = useState({
    cutoff: 0,
    color: "#87CEEB",
    widthCm: 15,
    heightCm: 10,
    dpi: 100,
  });

  const [coverage, setCoverage] = useState({
    includeId: false,
    header: true,
    legend: true,
    mode: "Normal",
    colorClassI: "#2563eb",
    colorNotClassI: "#f59e0b",
    conditions: [] as string[],
    widthCm: 20,
    heightCm: 10,
    dpi: 300,
  });

  const [distribution, setDistribution] = useState({
    cutoff: 0,
    header: true,
    color: "#87CEEB",
    widthCm: 20,
    heightCm: 15,
    dpi: 300,
  });

  const [sty, setSty] = useState({
    header: true,
    widthCm: 17.78,
    heightCm: 11.43,
    dpi: 140,
  });

  const [ksea, setKsea] = useState({
    condition1: "",
    condition2: "",
    pValueThreshold: 0.05,
    log2fcThreshold: 1,
    testType: "unpaired",
    useUncorrected: false,
    header: true,
    widthCm: 20,
    heightCm: 12,
    dpi: 220,
  });

  const [phosprotRegulation, setPhosprotRegulation] = useState({
    condition1: "",
    condition2: "",
    pValueThreshold: 0.05,
    log2fcThreshold: 1,
    testType: "unpaired",
    useUncorrected: false,
    maxHoverSites: 20,
    showPhosphosites: true,
    header: true,
    widthCm: 20,
    heightCm: 12,
    dpi: 220,
  });
  const debouncedPhosphositePlot = useDebouncedValue(phosphositePlot, 650);
  const debouncedCoverage = useDebouncedValue(coverage, 650);
  const debouncedDistribution = useDebouncedValue(distribution, 650);
  const debouncedSty = useDebouncedValue(sty, 650);
  const debouncedKsea = useDebouncedValue(ksea, 650);
  const debouncedPhosprotRegulation = useDebouncedValue(phosprotRegulation, 650);

  useEffect(() => {
    if (!hasPhosphoDataset) {
      setOptions(null);
      setOptionsLoading(false);
      setOptionsError("No phospho dataset loaded.");
      return;
    }
    let cancelled = false;
    setOptionsLoading(true);
    setOptionsError(null);
    getPhosphoOptions()
      .then((data) => {
        if (cancelled) return;
        setOptions(data);
      })
      .catch((err) => {
        if (cancelled) return;
        setOptions(null);
        setOptionsError(err instanceof Error ? err.message : "Failed to load phospho options");
      })
      .finally(() => {
        if (cancelled) return;
        setOptionsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [hasPhosphoDataset]);

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
    setKsea((prev) => {
      const nextCondition1 = conditionOptions.includes(prev.condition1) ? prev.condition1 : conditionOptions[0];
      const nextCondition2 = conditionOptions.includes(prev.condition2) && prev.condition2 !== nextCondition1
        ? prev.condition2
        : conditionOptions.find((value) => value !== nextCondition1) ?? nextCondition1;
      return { ...prev, condition1: nextCondition1, condition2: nextCondition2 };
    });
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
          widthCm: debouncedCoverage.widthCm,
          heightCm: debouncedCoverage.heightCm,
          dpi: debouncedCoverage.dpi,
          conditions: debouncedCoverage.conditions.join(","),
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

    if (activeTab === "ksea") {
      if (!debouncedKsea.condition1 || !debouncedKsea.condition2) return null;
      return {
        title: "KSEA",
        filename: "ksea_plot.png",
        type: "image",
        url: buildPlotUrl("/api/plots/phospho/ksea.png", {
          condition1: debouncedKsea.condition1,
          condition2: debouncedKsea.condition2,
          pValueThreshold: debouncedKsea.pValueThreshold,
          log2fcThreshold: debouncedKsea.log2fcThreshold,
          testType: debouncedKsea.testType,
          useUncorrected: debouncedKsea.useUncorrected,
          header: debouncedKsea.header,
          widthCm: debouncedKsea.widthCm,
          heightCm: debouncedKsea.heightCm,
          dpi: debouncedKsea.dpi,
        }),
      };
    }

    if (activeTab === "phosprotRegulation") {
      if (!debouncedPhosprotRegulation.condition1 || !debouncedPhosprotRegulation.condition2) return null;
      if (debouncedPhosprotRegulation.condition1 === debouncedPhosprotRegulation.condition2) return null;
      return {
        title: "Phosprot Regulation",
        filename: "phosprot_regulation.html",
        type: "html",
        url: buildPlotUrl("/api/plots/phospho/phosprot-regulation.html", {
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
    debouncedKsea,
    debouncedPhosprotRegulation,
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
        conditions: debouncedCoverage.conditions.join(","),
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

    if (activeTab === "ksea") {
      if (!debouncedKsea.condition1 || !debouncedKsea.condition2) return null;
      const params: Record<string, string | number | boolean> = {
        condition1: debouncedKsea.condition1,
        condition2: debouncedKsea.condition2,
        pValueThreshold: debouncedKsea.pValueThreshold,
        log2fcThreshold: debouncedKsea.log2fcThreshold,
        testType: debouncedKsea.testType,
        useUncorrected: debouncedKsea.useUncorrected,
      };
      return {
        tab: "ksea",
        params,
      };
    }

    if (activeTab === "phosprotRegulation") {
      if (!debouncedPhosprotRegulation.condition1 || !debouncedPhosprotRegulation.condition2) return null;
      if (debouncedPhosprotRegulation.condition1 === debouncedPhosprotRegulation.condition2) return null;
      const params: Record<string, string | number | boolean> = {
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
    debouncedKsea,
    debouncedPhosprotRegulation,
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

    let cancelled = false;
    setTableLoading(true);
    setTableError(null);
    getPhosphoTable(tableRequest.tab, tableRequest.params)
      .then((payload) => {
        if (cancelled) return;
        setTableRows(payload.rows ?? []);
      })
      .catch((err) => {
        if (cancelled) return;
        setTableRows([]);
        setTableError(err instanceof Error ? err.message : "Failed to load phospho table");
      })
      .finally(() => {
        if (cancelled) return;
        setTableLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [tableRequest, hasPhosphoDataset]);

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

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Phospho-specific Pipeline</h2>
      </section>

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

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-900">{plotTitle(activeTab)}</h3>
          {hasPhosphoDataset && plotView && plotView.type === "image" ? (
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
                key={plotView.url}
                src={plotView.url}
                title={plotView.title}
                className="h-[40rem] w-full rounded-xl border border-slate-200"
              />
            ) : (
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
            )}
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
            Select required options to render the plot.
          </div>
        )}

        {imageError ? (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {imageError}
          </div>
        ) : null}
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
            <ColorField
              key="color"
              label="Bar Color"
              value={phosphositePlot.color}
              onChange={(value) => setPhosphositePlot({ ...phosphositePlot, color: value })}
            />,
          ]}
          sizeRow={
            <SizeRow
              widthCm={phosphositePlot.widthCm}
              heightCm={phosphositePlot.heightCm}
              dpi={phosphositePlot.dpi}
              onWidthChange={(value) => setPhosphositePlot({ ...phosphositePlot, widthCm: Math.max(1, value) })}
              onHeightChange={(value) => setPhosphositePlot({ ...phosphositePlot, heightCm: Math.max(1, value) })}
              onDpiChange={(value) => setPhosphositePlot({ ...phosphositePlot, dpi: Math.max(72, Math.round(value)) })}
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
            <ColorField
              key="classI"
              label="Class I Color"
              value={coverage.colorClassI}
              onChange={(value) => setCoverage({ ...coverage, colorClassI: value })}
            />,
            <ColorField
              key="notClassI"
              label="Not Class I Color"
              value={coverage.colorNotClassI}
              onChange={(value) => setCoverage({ ...coverage, colorNotClassI: value })}
            />,
          ]}
          toggles={[
            <Checkbox key="id" label="Toggle ID" checked={coverage.includeId} onChange={(value) => setCoverage({ ...coverage, includeId: value })} />,
            <Checkbox key="header" label="Toggle Header" checked={coverage.header} onChange={(value) => setCoverage({ ...coverage, header: value })} />,
            <Checkbox key="legend" label="Toggle Legend" checked={coverage.legend} onChange={(value) => setCoverage({ ...coverage, legend: value })} />,
          ]}
          sizeRow={
            <SizeRow
              widthCm={coverage.widthCm}
              heightCm={coverage.heightCm}
              dpi={coverage.dpi}
              onWidthChange={(value) => setCoverage({ ...coverage, widthCm: Math.max(1, value) })}
              onHeightChange={(value) => setCoverage({ ...coverage, heightCm: Math.max(1, value) })}
              onDpiChange={(value) => setCoverage({ ...coverage, dpi: Math.max(72, Math.round(value)) })}
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
            <ColorField
              key="color"
              label="Bar Color"
              value={distribution.color}
              onChange={(value) => setDistribution({ ...distribution, color: value })}
            />,
          ]}
          toggles={[
            <Checkbox key="header" label="Toggle Header" checked={distribution.header} onChange={(value) => setDistribution({ ...distribution, header: value })} />,
          ]}
          sizeRow={
            <SizeRow
              widthCm={distribution.widthCm}
              heightCm={distribution.heightCm}
              dpi={distribution.dpi}
              onWidthChange={(value) => setDistribution({ ...distribution, widthCm: Math.max(1, value) })}
              onHeightChange={(value) => setDistribution({ ...distribution, heightCm: Math.max(1, value) })}
              onDpiChange={(value) => setDistribution({ ...distribution, dpi: Math.max(72, Math.round(value)) })}
            />
          }
        />
      );
    }

    if (activeTab === "ksea") {
      const condition2Options = conditionOptions.filter((value) => value !== ksea.condition1);
      return (
        <OptionsLayout
          fields={[
            <SelectField
              key="condition1"
              label="Condition 1"
              value={ksea.condition1}
              options={conditionOptions}
              onChange={(value) => {
                const fallback = conditionOptions.find((option) => option !== value) ?? value;
                setKsea({ ...ksea, condition1: value, condition2: ksea.condition2 === value ? fallback : ksea.condition2 });
              }}
            />,
            <SelectField
              key="condition2"
              label="Condition 2"
              value={ksea.condition2}
              options={condition2Options.length > 0 ? condition2Options : conditionOptions}
              onChange={(value) => setKsea({ ...ksea, condition2: value })}
            />,
            <NumericField
              key="pValueThreshold"
              label="P-value Threshold"
              value={ksea.pValueThreshold}
              onChange={(value) => setKsea({ ...ksea, pValueThreshold: Math.max(1e-12, Math.min(1, value)) })}
            />,
            <NumericField
              key="log2fcThreshold"
              label="log2 FC Threshold"
              value={ksea.log2fcThreshold}
              onChange={(value) => setKsea({ ...ksea, log2fcThreshold: Math.max(0, value) })}
            />,
            <SelectField
              key="testType"
              label="Test Type"
              value={ksea.testType}
              options={["unpaired", "paired"]}
              onChange={(value) => setKsea({ ...ksea, testType: value })}
            />,
          ]}
          toggles={[
            <Checkbox key="uncorrected" label="Use Uncorrected P-values" checked={ksea.useUncorrected} onChange={(value) => setKsea({ ...ksea, useUncorrected: value })} />,
            <Checkbox key="header" label="Toggle Header" checked={ksea.header} onChange={(value) => setKsea({ ...ksea, header: value })} />,
          ]}
          sizeRow={
            <SizeRow
              widthCm={ksea.widthCm}
              heightCm={ksea.heightCm}
              dpi={ksea.dpi}
              onWidthChange={(value) => setKsea({ ...ksea, widthCm: Math.max(1, value) })}
              onHeightChange={(value) => setKsea({ ...ksea, heightCm: Math.max(1, value) })}
              onDpiChange={(value) => setKsea({ ...ksea, dpi: Math.max(72, Math.round(value)) })}
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
              options={["unpaired", "paired"]}
              onChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, testType: value })}
            />,
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
            <Checkbox key="header" label="Toggle Header" checked={phosprotRegulation.header} onChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, header: value })} />,
          ]}
          sizeRow={
            <SizeRow
              widthCm={phosprotRegulation.widthCm}
              heightCm={phosprotRegulation.heightCm}
              dpi={phosprotRegulation.dpi}
              onWidthChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, widthCm: Math.max(1, value) })}
              onHeightChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, heightCm: Math.max(1, value) })}
              onDpiChange={(value) => setPhosprotRegulation({ ...phosprotRegulation, dpi: Math.max(72, Math.round(value)) })}
            />
          }
        />
      );
    }

    return (
      <OptionsLayout
        fields={[]}
        toggles={[
          <Checkbox key="header" label="Toggle Header" checked={sty.header} onChange={(value) => setSty({ ...sty, header: value })} />,
        ]}
        sizeRow={
          <SizeRow
            widthCm={sty.widthCm}
            heightCm={sty.heightCm}
            dpi={sty.dpi}
            onWidthChange={(value) => setSty({ ...sty, widthCm: Math.max(1, value) })}
            onHeightChange={(value) => setSty({ ...sty, heightCm: Math.max(1, value) })}
            onDpiChange={(value) => setSty({ ...sty, dpi: Math.max(72, Math.round(value)) })}
          />
        }
      />
    );
  }
}

function plotTitle(tab: PhosphoTab): string {
  if (tab === "phosphositePlot") return "Phosphosite Plot";
  if (tab === "coverage") return "Phosphosite Coverage Plot";
  if (tab === "ksea") return "KSEA";
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

function SizeRow({
  widthCm,
  heightCm,
  dpi,
  onWidthChange,
  onHeightChange,
  onDpiChange,
}: {
  widthCm: number;
  heightCm: number;
  dpi: number;
  onWidthChange: (value: number) => void;
  onHeightChange: (value: number) => void;
  onDpiChange: (value: number) => void;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <NumericField label="Width (cm)" value={widthCm} onChange={onWidthChange} />
      <NumericField label="Height (cm)" value={heightCm} onChange={onHeightChange} />
      <NumericField label="DPI" value={dpi} onChange={onDpiChange} />
    </div>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function MultiSelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string[];
  options: string[];
  onChange: (value: string[]) => void;
}) {
  const visibleRows = Math.max(4, Math.min(8, options.length || 4));
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <select
        multiple
        size={visibleRows}
        value={value}
        onChange={(event) => {
          const selected = Array.from(event.currentTarget.selectedOptions).map((option) => option.value);
          onChange(selected);
        }}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      <span className="mt-1 block text-xs text-slate-500">Use Ctrl/Cmd-click for multi-select.</span>
    </label>
  );
}

function NumericField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  const [draft, setDraft] = useState(() => (Number.isFinite(value) ? String(value) : ""));

  useEffect(() => {
    setDraft(Number.isFinite(value) ? String(value) : "");
  }, [value]);

  const commit = () => {
    const normalized = draft.trim().replace(",", ".");
    if (!normalized) {
      setDraft(Number.isFinite(value) ? String(value) : "");
      return;
    }
    const parsed = Number(normalized);
    if (!Number.isFinite(parsed)) {
      setDraft(Number.isFinite(value) ? String(value) : "");
      return;
    }
    onChange(parsed);
    setDraft(String(parsed));
  };

  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <input
        type="text"
        lang="en-US"
        inputMode="decimal"
        value={draft}
        onChange={(event) => {
          const normalized = event.target.value.replace(",", ".");
          setDraft(normalized);
          const parsed = Number(normalized);
          if (Number.isFinite(parsed)) {
            onChange(parsed);
          }
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
        }}
        className="w-full rounded-xl border border-slate-300 px-3 py-2 outline-none focus:border-slate-900"
      />
    </label>
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
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <input
        type="color"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-xl border border-slate-300 bg-white px-2 py-1"
      />
    </label>
  );
}

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-500"
      />
      {label}
    </label>
  );
}

function PreviewTable({
  rows,
  emptyText,
}: {
  rows: Record<string, unknown>[];
  emptyText: string;
}) {
  return <PaginatedTable rows={rows} pageSize={50} emptyText={emptyText} maxHeightClassName="max-h-[28rem]" />;
}

function collectColumns(rows: Record<string, unknown>[]) {
  const keys = new Set<string>();
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => keys.add(key));
  });
  return Array.from(keys);
}

function rowsToCsv(rows: Record<string, unknown>[], columns: string[]) {
  const header = columns.join(",");
  const body = rows.map((row) =>
    columns
      .map((column) => {
        const raw = row[column];
        const text = raw == null ? "" : String(raw);
        if (text.includes(",") || text.includes('"') || text.includes("\n")) {
          return `"${text.replace(/"/g, '""')}"`;
        }
        return text;
      })
      .join(",")
  );
  return [header, ...body].join("\n");
}

