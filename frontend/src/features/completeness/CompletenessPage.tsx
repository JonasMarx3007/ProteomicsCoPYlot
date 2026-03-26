import { useEffect, useMemo, useState, type ReactNode } from "react";
import { buildPlotUrl, getCompletenessTables } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import {
  PLOT_DOWNLOAD_FORMAT_OPTIONS,
  type PlotDownloadFormat,
  withPlotDownloadFilename,
  withPlotDownloadFormat,
} from "../../lib/plotDownload";
import type { AnnotationKind, CompletenessTab, CompletenessTablesResponse } from "../../lib/types";

type Props = {
  activeTab: CompletenessTab;
};

type CompletenessKind = AnnotationKind | "peptide" | "precursor";

function isAnnotationKind(kind: CompletenessKind): kind is AnnotationKind {
  return kind === "protein" || kind === "phospho" || kind === "phosprot";
}

export default function CompletenessPage({ activeTab }: Props) {
  const [kind, setKind] = useState<CompletenessKind>("protein");
  const { datasets, availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [imageError, setImageError] = useState<string | null>(null);
  const [tableData, setTableData] = useState<CompletenessTablesResponse | null>(null);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>("png");

  const [missingPlot, setMissingPlot] = useState({
    header: true,
    text: true,
    binCount: 0,
    textSize: 8,
    color: "#2563eb",
    widthCm: 20,
    heightCm: 10,
    dpi: 300,
  });
  const [heatmap, setHeatmap] = useState({
    includeId: true,
    header: true,
    widthCm: 10,
    heightCm: 10,
    dpi: 300,
  });
  const [tables, setTables] = useState({
    includeId: true,
    outlierThreshold: 50,
  });

  const activeKindOptions = useMemo<Array<{ value: CompletenessKind; label: string }>>(() => {
    if (activeTab !== "missingPlot") return kindOptions;
    const options: Array<{ value: CompletenessKind; label: string }> = [...kindOptions];
    if (datasets?.peptide) {
      options.push({ value: "peptide", label: "Peptide" });
      options.push({ value: "precursor", label: "Precursor" });
    }
    return options;
  }, [activeTab, kindOptions, datasets]);

  async function loadTables() {
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) {
      setTableData(null);
      setTableError("Please upload a protein, phospho, or phosphoprotein dataset first.");
      return;
    }
    try {
      setTableLoading(true);
      setTableError(null);
      const data = await getCompletenessTables(kind, {
        includeId: tables.includeId,
        outlierThreshold: tables.outlierThreshold,
      });
      setTableData(data);
    } catch (err) {
      setTableData(null);
      setTableError(err instanceof Error ? err.message : "Failed to load completeness tables");
    } finally {
      setTableLoading(false);
    }
  }

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
    if (activeTab !== "tables") return;
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) return;
    loadTables();
  }, [activeTab, kind, tables.includeId, tables.outlierThreshold, availableKinds]);

  const plotView = useMemo(() => {
    if (activeTab === "missingPlot") {
      return {
        title: "Missing Value Plot",
        filename: `completeness_missing_plot_${kind}.png`,
        url: buildPlotUrl(`/api/plots/completeness/${kind}/missing-value.png`, missingPlot),
      };
    }
    if (activeTab === "heatmap") {
      return {
        title: "Missing Value Heatmap",
        filename: `completeness_missing_heatmap_${kind}.png`,
        url: buildPlotUrl(`/api/plots/completeness/${kind}/missing-heatmap.png`, heatmap),
      };
    }
    return null;
  }, [activeTab, kind, missingPlot, heatmap]);
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
      </section>
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
              onClick={loadTables}
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

function SizeRow({
  dpi,
  heightCm,
  widthCm,
  onDpiChange,
  onHeightChange,
  onWidthChange,
}: {
  dpi: number;
  heightCm: number;
  widthCm: number;
  onDpiChange: (value: number) => void;
  onHeightChange: (value: number) => void;
  onWidthChange: (value: number) => void;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <NumericField label="DPI" value={dpi} onChange={onDpiChange} />
      <NumericField label="Height (cm)" value={heightCm} onChange={onHeightChange} />
      <NumericField label="Width (cm)" value={widthCm} onChange={onWidthChange} />
    </div>
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
    <label className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
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
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input
        type="text"
        lang="en-US"
        inputMode="decimal"
        value={draft}
        onChange={(e) => {
          const normalized = e.target.value.replace(",", ".");
          setDraft(normalized);
          const parsed = Number(normalized);
          if (Number.isFinite(parsed)) {
            onChange(parsed);
          }
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
        }}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
      />
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
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input
        type="color"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-10 w-full rounded-xl border border-slate-300 bg-white px-1 py-1"
      />
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-slate-900">{value}</div>
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

function collectColumns(rows: Record<string, unknown>[]): string[] {
  const seen = new Set<string>();
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => seen.add(key));
  });
  return Array.from(seen);
}

function rowsToCsv(rows: Record<string, unknown>[], columns: string[]): string {
  if (rows.length === 0 || columns.length === 0) return "";
  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const lines = [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => escape(row[column])).join(",")),
  ];
  return lines.join("\n");
}
