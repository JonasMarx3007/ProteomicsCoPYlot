import { collectColumns } from "../../lib/tableData";
import NotebookDownload from "../../components/NotebookDownload";
import { useEffect, useId, useMemo, useState } from "react";
import {
  downloadCurrentAnnotationMetadataData,
  generateSummaryReport,
  getSummaryTables,
} from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import { getSummaryReportContext } from "../../lib/reportState";
import type {
  SummaryTab,
  SummaryMetadataTable,
  SummaryReportResponse,
  SummaryTablesResponse,
} from "../../lib/types";

type TextPosition = "Above" | "Below";
type SummaryEditorState = {
  textEntries?: Record<string, unknown>;
  selectedPlot?: unknown;
  position?: unknown;
  editorValue?: unknown;
  showEntries?: unknown;
  reportTitle?: unknown;
  reportAuthor?: unknown;
};

const peptideTextKeys = ["CoveragePep", "MissingValuePep", "RT", "Modification", "MissedCleavage"] as const;
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

const SUMMARY_EDITOR_STATE_KEY = "summary.editor.v1";

const plotTextLabels: Record<string, string> = {
  Introduction: "Introduction",
  CoveragePep: "Coverage Plot - Peptide Level",
  MissingValuePep: "Missing Value Plot - Peptide Level",
  RT: "Retention Time Plot",
  Modification: "Modification Plot",
  MissedCleavage: "Missed Cleavage Plot",
  CoverageProt: "Coverage Plot - Protein Level",
  MissingValueProt: "Missing Value Plot - Protein Level",
  HistogramIntProt: "Histogram Intensity - Protein Level",
  BoxplotIntProt: "Boxplot Intensity - Protein Level",
  CovProt: "Coefficient of Variation - Protein Level",
  PCAProt: "PCA Plot - Protein Level",
  AbundanceProt: "Abundance Plot - Protein Level",
  CorrelationProt: "Correlation Plot - Protein Level",
  VolcanoProt: "Volcano Plot - Protein Level",
  Phossite: "Overview Phosphosites",
  "Coverage(Number)Phos": "Coverage Plot (Number) - Phosphosite Level",
  "Coverage(Quality)Phos": "Coverage Plot (Quality) - Phosphosite Level",
  MissingValuePhos: "Missing Value Plot - Phosphosite Level",
  HistogramIntPhos: "Histogram Intensity - Phosphosite Level",
  BoxplotIntPhos: "Boxplot Intensity - Phosphosite Level",
  CovPhos: "Coefficient of Variation - Phosphosite Level",
  PCAPhos: "PCA Plot - Phosphosite Level",
  AbundancePhos: "Abundance Plot - Phosphosite Level",
  CorrelationPhos: "Correlation Plot - Phosphosite Level",
  VolcanoPhos: "Volcano Plot - Phosphosite Level",
};

function plotTextLabel(key: string): string {
  return plotTextLabels[key] ?? key;
}

function asStringRecord(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object") return {};
  const entries = Object.entries(value as Record<string, unknown>);
  return Object.fromEntries(entries.map(([key, item]) => [key, String(item ?? "")]));
}

function asTextPosition(value: unknown): TextPosition {
  return String(value ?? "").trim() === "Below" ? "Below" : "Above";
}

export default function SummaryPage({ activeTab }: Props) {
  const plotFieldId = useId();
  const positionLabelId = useId();
  const textFieldId = useId();
  const persisted = useMemo(
    () => readPersistedUiState<SummaryEditorState>(SUMMARY_EDITOR_STATE_KEY, {}),
    []
  );
  const [tables, setTables] = useState<SummaryTablesResponse | null>(null);
  const [tablesLoading, setTablesLoading] = useState(false);
  const [tablesError, setTablesError] = useState<string | null>(null);
  const [tableDownloadBusyKey, setTableDownloadBusyKey] = useState<string | null>(null);

  const [textEntries, setTextEntries] = useState<Record<string, string>>(() =>
    asStringRecord(persisted.textEntries)
  );
  const [selectedPlot, setSelectedPlot] = useState(() =>
    String(persisted.selectedPlot ?? "Introduction")
  );
  const [position, setPosition] = useState<TextPosition>(() =>
    asTextPosition(persisted.position)
  );
  const [editorValue, setEditorValue] = useState(() =>
    String(persisted.editorValue ?? "")
  );
  const [showEntries, setShowEntries] = useState(() =>
    Boolean(persisted.showEntries ?? false)
  );

  const [reportTitle, setReportTitle] = useState(() =>
    String(persisted.reportTitle ?? "")
  );
  const [reportAuthor, setReportAuthor] = useState(() =>
    String(persisted.reportAuthor ?? "")
  );
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
    writePersistedUiState(SUMMARY_EDITOR_STATE_KEY, {
      textEntries,
      selectedPlot,
      position,
      editorValue,
      showEntries,
      reportTitle,
      reportAuthor,
    });
  }, [textEntries, selectedPlot, position, editorValue, showEntries, reportTitle, reportAuthor]);

  async function loadTables() {
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

  useEffect(() => {
    loadTables();
  }, []);

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
        reportContext: getSummaryReportContext(),
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

  async function handleDownloadMetadata(kind: SummaryMetadataTable["kind"]) {
    try {
      setTableDownloadBusyKey(kind);
      setTablesError(null);
      const { blob, filename } = await downloadCurrentAnnotationMetadataData(kind);
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setTablesError(err instanceof Error ? err.message : "Failed to download metadata table");
    } finally {
      setTableDownloadBusyKey(null);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Summary</h2>
      </section>

      {activeTab === "tables" ? (
        <div className="space-y-6">
          {tablesLoading ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              Loading tables...
            </div>
          ) : null}
          {tablesError ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {tablesError}
            </div>
          ) : null}

          <MetadataTableCard
            title="Protein Metadata"
            table={tables?.protein ?? null}
            downloadLabel="Download Protein Metadata"
            downloading={tableDownloadBusyKey === "protein"}
            downloadDisabled={tableDownloadBusyKey !== null}
            onDownload={() => handleDownloadMetadata("protein")}
          />
          <MetadataTableCard
            title="Phospho Metadata"
            table={tables?.phospho ?? null}
            downloadLabel="Download Phospho Metadata"
            downloading={tableDownloadBusyKey === "phospho"}
            downloadDisabled={tableDownloadBusyKey !== null}
            onDownload={() => handleDownloadMetadata("phospho")}
          />
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
                <label htmlFor={plotFieldId} className="mb-2 block text-sm font-medium text-slate-700">Select Plot</label>
                <select
                  id={plotFieldId}
                  value={selectedPlot}
                  onChange={(event) => setSelectedPlot(event.target.value)}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
                >
                  {plotOptions.map((option) => (
                    <option key={option} value={option}>
                      {plotTextLabel(option)}
                    </option>
                  ))}
                </select>
              </div>
              {selectedPlot !== "Introduction" ? (
                <div>
                  {/* A pair of buttons, not a field: named as a group. */}
                  <span id={positionLabelId} className="mb-2 block text-sm font-medium text-slate-700">Position</span>
                  <div role="group" aria-labelledby={positionLabelId} className="flex gap-2">
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
              <label htmlFor={textFieldId} className="mb-2 block text-sm font-medium text-slate-700">
                {selectedPlot === "Introduction" ? "Introduction Text" : "Text"}
              </label>
              <textarea
                id={textFieldId}
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
                <>
                  <a
                    href={downloadHref}
                    download={reportResult.fileName}
                    className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                  >
                    Download HTML Report
                  </a>
                  <NotebookDownload key={reportResult.notebookToken ?? 'unavailable'} plotUrl={downloadHref} outputLabel="report"
                    rendered={{ url: downloadHref, token: reportResult.notebookToken ?? null }} />
                </>
              ) : null}
            </div>
            {reportResult?.notebookError ? (
              <p role="alert" className="mt-3 text-sm text-amber-700">{reportResult.notebookError}</p>
            ) : null}
            {reportResult?.notebookToken && reportResult.notebookOmitted?.length ? (
              <p role="status" className="mt-3 text-sm text-amber-700">
                The notebook leaves out {reportResult.notebookOmitted.join("; ")}: their export could not be prepared.
              </p>
            ) : null}

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
                  sandbox="allow-scripts allow-downloads"
                  title="Summary Report"
                  srcDoc={reportResult.html}
                  className="w-full rounded-xl border border-slate-200"
                  style={{ height: "1240px" }}
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
  downloadLabel,
  downloading,
  downloadDisabled,
  onDownload,
}: {
  title: string;
  table: SummaryMetadataTable | null;
  downloadLabel: string;
  downloading: boolean;
  downloadDisabled: boolean;
  onDownload: () => void;
}) {
  const rows = useMemo(() => table?.table ?? [], [table?.table]);
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
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm text-slate-600">
              Rows: {table.rows} | Columns: {table.columns}
            </div>
            <button
              type="button"
              onClick={onDownload}
              disabled={downloadDisabled}
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400"
            >
              {downloading ? "Downloading..." : downloadLabel}
            </button>
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


function formatCell(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
