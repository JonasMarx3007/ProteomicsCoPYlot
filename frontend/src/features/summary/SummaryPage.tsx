import { useEffect, useMemo, useState } from "react";
import { generateSummaryReport, getSummaryTables } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import type {
  SummaryTab,
  SummaryMetadataTable,
  SummaryReportResponse,
  SummaryTablesResponse,
} from "../../lib/types";

type TextPosition = "Above" | "Below";

const peptideTextKeys = ["RT", "Modification", "MissedCleavage"] as const;
const proteinTextKeys = [
  "CoverageProt",
  "MissingValueProt",
  "HistogramIntProt",
  "BoxplotIntProt",
  "CovProt",
  "PCAProt",
  "AbundanceProt",
  "CorrelationProt",
  "VolcanoProt",
] as const;
const phosphoTextKeys = [
  "Phossite",
  "Coverage(Number)Phos",
  "Coverage(Quality)Phos",
  "MissingValuePhos",
  "HistogramIntPhos",
  "BoxplotIntPhos",
  "CovPhos",
  "PCAPhos",
  "AbundancePhos",
  "CorrelationPhos",
  "VolcanoPhos",
] as const;

type Props = {
  activeTab: SummaryTab;
};

export default function SummaryPage({ activeTab }: Props) {
  const [tables, setTables] = useState<SummaryTablesResponse | null>(null);
  const [tablesLoading, setTablesLoading] = useState(false);
  const [tablesError, setTablesError] = useState<string | null>(null);

  const [textEntries, setTextEntries] = useState<Record<string, string>>({});
  const [selectedPlot, setSelectedPlot] = useState("Introduction");
  const [position, setPosition] = useState<TextPosition>("Above");
  const [editorValue, setEditorValue] = useState("");
  const [showEntries, setShowEntries] = useState(false);

  const [reportTitle, setReportTitle] = useState("");
  const [reportAuthor, setReportAuthor] = useState("");
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);
  const [reportResult, setReportResult] = useState<SummaryReportResponse | null>(null);

  const { datasets } = useCurrentDatasetsSnapshot();

  const plotOptions = useMemo(() => {
    const options = ["Introduction"];
    if (datasets?.peptide) options.push(...peptideTextKeys);
    if (datasets?.protein) options.push(...proteinTextKeys);
    if (datasets?.phospho) options.push(...phosphoTextKeys);
    return options;
  }, [datasets]);

  const currentTextKey = useMemo(() => {
    if (selectedPlot === "Introduction") return "Introduction";
    return `${selectedPlot}${position}`;
  }, [selectedPlot, position]);

  useEffect(() => {
    if (!plotOptions.includes(selectedPlot)) {
      setSelectedPlot(plotOptions[0] ?? "Introduction");
    }
  }, [plotOptions, selectedPlot]);

  useEffect(() => {
    setEditorValue(textEntries[currentTextKey] ?? "");
  }, [currentTextKey, textEntries]);

  useEffect(() => {
    refreshTables();
  }, []);

  async function refreshTables() {
    try {
      setTablesLoading(true);
      setTablesError(null);
      const payload = await getSummaryTables();
      setTables(payload);
    } catch (err) {
      setTablesError(err instanceof Error ? err.message : "Failed to load summary tables");
      setTables(null);
    } finally {
      setTablesLoading(false);
    }
  }

  function saveCurrentText() {
    const trimmed = editorValue.trim();
    if (!trimmed) return;
    setTextEntries((prev) => ({ ...prev, [currentTextKey]: trimmed }));
  }

  function deleteCurrentText() {
    setTextEntries((prev) => {
      const next = { ...prev };
      delete next[currentTextKey];
      return next;
    });
    setEditorValue("");
  }

  async function createReport() {
    try {
      setReportLoading(true);
      setReportError(null);
      const response = await generateSummaryReport({
        title: reportTitle,
        author: reportAuthor,
        textEntries,
      });
      setReportResult(response);
    } catch (err) {
      setReportResult(null);
      setReportError(err instanceof Error ? err.message : "Failed to generate report");
    } finally {
      setReportLoading(false);
    }
  }

  const downloadHref = useMemo(() => {
    if (!reportResult) return null;
    return `data:text/html;charset=utf-8,${encodeURIComponent(reportResult.html)}`;
  }, [reportResult]);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Summary</h2>
      </section>

      {activeTab === "tables" ? (
        <div className="space-y-6">
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-slate-900">Metadata Tables</h3>
              <button
                type="button"
                onClick={refreshTables}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Refresh
              </button>
            </div>
            {tablesLoading ? (
              <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                Loading tables...
              </div>
            ) : null}
            {tablesError ? (
              <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {tablesError}
              </div>
            ) : null}
          </section>

          <MetadataTableCard title="Normal Data Metadata" table={tables?.protein ?? null} />
          <MetadataTableCard title="Phospho Data Metadata" table={tables?.phospho ?? null} />
        </div>
      ) : null}

      {activeTab === "text" ? (
        <div className="space-y-6">
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">Report Text Blocks</h3>
            <p className="mt-2 text-sm text-slate-600">
              Add optional text above or below report plots. These entries are used when generating the HTML report.
            </p>

            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">Select Plot</label>
                <select
                  value={selectedPlot}
                  onChange={(event) => setSelectedPlot(event.target.value)}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
                >
                  {plotOptions.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </div>
              {selectedPlot !== "Introduction" ? (
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700">Position</label>
                  <div className="flex gap-2">
                    <TabButton
                      label="Above"
                      active={position === "Above"}
                      onClick={() => setPosition("Above")}
                    />
                    <TabButton
                      label="Below"
                      active={position === "Below"}
                      onClick={() => setPosition("Below")}
                    />
                  </div>
                </div>
              ) : null}
            </div>

            <div className="mt-4">
              <label className="mb-2 block text-sm font-medium text-slate-700">
                {selectedPlot === "Introduction" ? "Introduction Text" : "Text"}
              </label>
              <textarea
                value={editorValue}
                onChange={(event) => setEditorValue(event.target.value)}
                rows={8}
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
              />
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={saveCurrentText}
                className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800"
              >
                Add / Update
              </button>
              <button
                type="button"
                onClick={deleteCurrentText}
                className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Delete
              </button>
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <label className="inline-flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={showEntries}
                onChange={(event) => setShowEntries(event.target.checked)}
              />
              Show stored text entries
            </label>
            {showEntries ? (
              <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
                {Object.keys(textEntries).length === 0 ? (
                  <div className="text-sm text-slate-500">No stored entries yet.</div>
                ) : (
                  <pre className="overflow-auto whitespace-pre-wrap text-xs text-slate-700">
                    {JSON.stringify(textEntries, null, 2)}
                  </pre>
                )}
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      {activeTab === "report" ? (
        <div className="space-y-6">
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">Report Generator</h3>

            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              <label className="block text-sm">
                <span className="mb-2 block font-medium text-slate-700">Report Title</span>
                <input
                  type="text"
                  value={reportTitle}
                  onChange={(event) => setReportTitle(event.target.value)}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
                />
              </label>
              <label className="block text-sm">
                <span className="mb-2 block font-medium text-slate-700">Author</span>
                <input
                  type="text"
                  value={reportAuthor}
                  onChange={(event) => setReportAuthor(event.target.value)}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
                />
              </label>
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={createReport}
                disabled={reportLoading}
                className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {reportLoading ? "Generating..." : "Generate HTML Report"}
              </button>
              {downloadHref && reportResult ? (
                <a
                  href={downloadHref}
                  download={reportResult.fileName}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                >
                  Download HTML Report
                </a>
              ) : null}
            </div>

            {reportError ? (
              <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {reportError}
              </div>
            ) : null}
          </section>

          {reportResult?.warnings?.length ? (
            <section className="rounded-2xl border border-amber-200 bg-amber-50 p-6 shadow-sm">
              <h3 className="text-lg font-semibold text-amber-900">Report Warnings</h3>
              <ul className="mt-3 list-disc pl-5 text-sm text-amber-900">
                {reportResult.warnings.map((warning, index) => (
                  <li key={`${warning}-${index}`}>{warning}</li>
                ))}
              </ul>
            </section>
          ) : null}

          {reportResult ? (
            <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-lg font-semibold text-slate-900">Report Preview</h3>
              <div className="mt-4">
                <iframe
                  title="Summary Report"
                  srcDoc={reportResult.html}
                  className="w-full rounded-xl border border-slate-200"
                  style={{ height: "840px" }}
                />
              </div>
            </section>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function TabButton({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "rounded-xl border px-3 py-2 text-sm transition",
        active
          ? "border-slate-900 bg-slate-900 text-white"
          : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

function MetadataTableCard({
  title,
  table,
}: {
  title: string;
  table: SummaryMetadataTable | null;
}) {
  const rows = table?.table ?? [];
  const columns = useMemo(() => collectColumns(rows), [rows]);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
      {!table || !table.available ? (
        <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
          Metadata not available yet.
        </div>
      ) : (
        <>
          <div className="mt-3 text-sm text-slate-600">
            Rows: {table.rows} | Columns: {table.columns}
          </div>
          <div className="mt-4">
            {rows.length === 0 || columns.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                No table rows available.
              </div>
            ) : (
              <div className="max-h-[28rem] overflow-auto rounded-xl border border-slate-200">
                <table className="min-w-full table-fixed border-collapse text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      {columns.map((column) => (
                        <th
                          key={column}
                          className="border-b border-slate-200 px-3 py-2 text-left font-medium text-slate-700"
                        >
                          {column}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, rowIndex) => (
                      <tr key={rowIndex} className="odd:bg-white even:bg-slate-50/50">
                        {columns.map((column) => (
                          <td
                            key={`${rowIndex}-${column}`}
                            className="border-b border-slate-100 px-3 py-2 text-slate-600"
                          >
                            {formatCell(row[column])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function collectColumns(rows: Record<string, unknown>[]): string[] {
  const seen = new Set<string>();
  rows.forEach((row) => {
    Object.keys(row).forEach((key) => seen.add(key));
  });
  return Array.from(seen);
}

function formatCell(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
