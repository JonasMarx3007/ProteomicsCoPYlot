import { useEffect, useMemo, useState } from "react";
import {
  getPhosphoOptions,
  getPhosphoTable,
  renderKseaVolcanoFromFiles,
} from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import type { PhosphoOptionsResponse } from "../../lib/types";

export default function KseaPage() {
  const { datasets } = useCurrentDatasetsSnapshot();
  const hasPhosphoDataset = Boolean(datasets?.phospho);
  const [options, setOptions] = useState<PhosphoOptionsResponse | null>(null);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);

  const [condition1, setCondition1] = useState("");
  const [condition2, setCondition2] = useState("");
  const [pValueThreshold, setPValueThreshold] = useState(0.05);
  const [log2fcThreshold, setLog2fcThreshold] = useState(1.0);
  const [testType, setTestType] = useState<"unpaired" | "paired">("unpaired");
  const [useUncorrected, setUseUncorrected] = useState(false);

  const [tableRows, setTableRows] = useState<Record<string, unknown>[]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);

  const [fileSt, setFileSt] = useState<File | null>(null);
  const [fileTnc, setFileTnc] = useState<File | null>(null);
  const [volcanoPValueThreshold, setVolcanoPValueThreshold] = useState(0.1);
  const [volcanoHeader, setVolcanoHeader] = useState(true);
  const [highlightGrk, setHighlightGrk] = useState(false);
  const [volcanoHtml, setVolcanoHtml] = useState("");
  const [volcanoLoading, setVolcanoLoading] = useState(false);
  const [volcanoError, setVolcanoError] = useState<string | null>(null);

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
      .then((payload) => {
        if (cancelled) return;
        setOptions(payload);
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
    if (conditionOptions.length === 0) return;
    const first = conditionOptions[0];
    setCondition1((prev) => (conditionOptions.includes(prev) ? prev : first));
    setCondition2((prev) => (conditionOptions.includes(prev) ? prev : first));
  }, [options]);

  const validComparison =
    condition1.trim() !== "" &&
    condition2.trim() !== "" &&
    condition1 !== condition2;

  useEffect(() => {
    if (!hasPhosphoDataset) {
      setTableRows([]);
      setTableLoading(false);
      setTableError("No phospho dataset loaded.");
      return;
    }
    if (!validComparison) {
      setTableRows([]);
      setTableLoading(false);
      setTableError(null);
      return;
    }
    let cancelled = false;
    setTableLoading(true);
    setTableError(null);
    getPhosphoTable("ksea", {
      condition1,
      condition2,
      pValueThreshold,
      log2fcThreshold,
      testType,
      useUncorrected,
    })
      .then((payload) => {
        if (cancelled) return;
        setTableRows(payload.rows ?? []);
      })
      .catch((err) => {
        if (cancelled) return;
        setTableRows([]);
        setTableError(err instanceof Error ? err.message : "Failed to load KSEA table");
      })
      .finally(() => {
        if (cancelled) return;
        setTableLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    hasPhosphoDataset,
    validComparison,
    condition1,
    condition2,
    pValueThreshold,
    log2fcThreshold,
    testType,
    useUncorrected,
  ]);

  const tsvDownload = useMemo(() => {
    if (tableRows.length === 0) return null;
    const columns = collectColumns(tableRows);
    if (columns.length === 0) return null;
    const body = rowsToDelimited(tableRows, columns, "\t");
    return `data:text/tab-separated-values;charset=utf-8,${encodeURIComponent(body)}`;
  }, [tableRows]);

  async function generateVolcano() {
    if (!(fileSt && fileTnc)) {
      setVolcanoError("Please upload both KSEA result files.");
      return;
    }
    if (!validComparison) {
      setVolcanoError("Please select two different conditions to generate the plot.");
      return;
    }
    setVolcanoLoading(true);
    setVolcanoError(null);
    try {
      const html = await renderKseaVolcanoFromFiles({
        fileSt,
        fileTnc,
        pValueThreshold: volcanoPValueThreshold,
        header: volcanoHeader,
        condition1,
        condition2,
        highlightGrk,
      });
      setVolcanoHtml(html);
    } catch (err) {
      setVolcanoHtml("");
      setVolcanoError(err instanceof Error ? err.message : "Failed to generate KSEA volcano");
    } finally {
      setVolcanoLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">KSEA</h2>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">KSEA Input Table</h3>
        {!hasPhosphoDataset ? (
          <InfoNotice message="No phospho dataset loaded. Upload data in the Data tab first." />
        ) : optionsLoading ? (
          <NeutralNotice message="Loading options..." />
        ) : optionsError ? (
          <ErrorNotice message={optionsError} />
        ) : (
          <div className="mt-4 space-y-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <SelectField
                label="Condition 1"
                value={condition1}
                options={options?.conditions ?? []}
                onChange={setCondition1}
              />
              <SelectField
                label="Condition 2"
                value={condition2}
                options={options?.conditions ?? []}
                onChange={setCondition2}
              />
              <NumericField
                label="P-value Threshold"
                value={pValueThreshold}
                onChange={(value) => setPValueThreshold(Math.max(1e-12, Math.min(1, value)))}
              />
              <NumericField
                label="log2 FC Threshold"
                value={log2fcThreshold}
                onChange={(value) => setLog2fcThreshold(Math.max(0, value))}
              />
              <SelectField
                label="Test Type"
                value={testType}
                options={["unpaired", "paired"]}
                onChange={(value) => setTestType(value as "unpaired" | "paired")}
              />
            </div>
            <div className="flex flex-wrap gap-3">
              <Checkbox
                label="Use Uncorrected P-values"
                checked={useUncorrected}
                onChange={setUseUncorrected}
              />
            </div>
            {!validComparison ? (
              <InfoNotice message="Please select two different conditions to generate the plot." />
            ) : tableLoading ? (
              <NeutralNotice message="Loading KSEA input table..." />
            ) : tableError ? (
              <ErrorNotice message={tableError} />
            ) : (
              <>
                {tsvDownload ? (
                  <a
                    href={tsvDownload}
                    download={`KSEA_${condition1}_vs_${condition2}.tsv`}
                    className="inline-flex rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                  >
                    Download KSEA Table (TSV)
                  </a>
                ) : null}
                <PreviewTable rows={tableRows} emptyText="No rows available for the current selection." />
              </>
            )}
          </div>
        )}
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Instructions</h3>
        <ol className="mt-4 list-decimal space-y-2 pl-5 text-sm text-slate-700">
          <li>Select two conditions and download the prepared KSEA table (TSV).</li>
          <li>Open <a className="text-sky-700 underline" href="https://www.phosphosite.org/kinaseLibraryAction" target="_blank" rel="noreferrer">PhosphoSitePlus Kinase Library</a>.</li>
          <li>Go to <strong>Fisher Enrichment Analysis</strong> and upload the downloaded table.</li>
          <li>Set columns as in the original workflow:
            <div>Motif column: <code>UPD_seq</code></div>
            <div>log2FC column: <code>log2FC</code></div>
            <div>p-value column (optional): <code>pval</code> or <code>adj_pval</code></div>
          </li>
          <li>Run analysis for Serine/Threonine and again for Tyrosine/non-canonical kinases.</li>
          <li>Download both result files and upload them below to generate the KSEA volcano.</li>
        </ol>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">KSEA Volcano From Uploaded Results</h3>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <FileField
            label="Serine/Threonine Result File"
            onFile={(file) => setFileSt(file)}
            helpText={fileSt ? fileSt.name : "Upload .csv, .tsv, or .txt"}
          />
          <FileField
            label="Tyrosine/Non-canonical Result File"
            onFile={(file) => setFileTnc(file)}
            helpText={fileTnc ? fileTnc.name : "Upload .csv, .tsv, or .txt"}
          />
          <NumericField
            label="KSEA Volcano P-value Threshold"
            value={volcanoPValueThreshold}
            onChange={(value) => setVolcanoPValueThreshold(Math.max(1e-12, Math.min(1, value)))}
          />
        </div>
        <div className="mt-4 flex flex-wrap gap-3">
          <Checkbox label="Toggle Header" checked={volcanoHeader} onChange={setVolcanoHeader} />
          <Checkbox label="Highlight GRK Kinases" checked={highlightGrk} onChange={setHighlightGrk} />
        </div>
        {!validComparison ? (
          <div className="mt-4">
            <InfoNotice message="Please select two different conditions to generate the plot." />
          </div>
        ) : null}
        <div className="mt-4">
          <button
            type="button"
            onClick={generateVolcano}
            disabled={volcanoLoading || !fileSt || !fileTnc || !validComparison}
            className="rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {volcanoLoading ? "Generating..." : "Generate KSEA Volcano"}
          </button>
        </div>
        {volcanoError ? (
          <div className="mt-4">
            <ErrorNotice message={volcanoError} />
          </div>
        ) : null}
        {volcanoHtml ? (
          <div className="mt-4">
            <iframe
              srcDoc={volcanoHtml}
              title="KSEA Volcano"
              className="h-[40rem] w-full rounded-xl border border-slate-200"
            />
          </div>
        ) : null}
      </section>
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
        onChange={(event) => onChange(event.target.value)}
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
          if (Number.isFinite(parsed)) onChange(parsed);
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

function FileField({
  label,
  onFile,
  helpText,
}: {
  label: string;
  onFile: (file: File | null) => void;
  helpText: string;
}) {
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <input
        type="file"
        accept=".csv,.tsv,.txt"
        onChange={(event) => onFile(event.currentTarget.files?.[0] ?? null)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-1 file:text-slate-700 hover:file:bg-slate-200"
      />
      <span className="mt-1 block text-xs text-slate-500">{helpText}</span>
    </label>
  );
}

function InfoNotice({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
      {message}
    </div>
  );
}

function NeutralNotice({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">
      {message}
    </div>
  );
}

function ErrorNotice({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {message}
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
  if (!rows || rows.length === 0) {
    return (
      <NeutralNotice message={emptyText} />
    );
  }
  const columns = collectColumns(rows);
  return (
    <div className="max-h-[28rem] overflow-auto rounded-xl border border-slate-200">
      <table className="min-w-full divide-y divide-slate-200">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((column) => (
              <th key={column} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-600">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {rows.map((row, index) => (
            <tr key={index} className={index % 2 ? "bg-slate-50/40" : "bg-white"}>
              {columns.map((column) => (
                <td key={column} className="px-4 py-2 align-top text-sm text-slate-700">
                  {formatValue(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function collectColumns(rows: Record<string, unknown>[]) {
  const keys = new Set<string>();
  rows.forEach((row) => Object.keys(row).forEach((key) => keys.add(key)));
  return Array.from(keys);
}

function rowsToDelimited(rows: Record<string, unknown>[], columns: string[], delimiter: string) {
  const header = columns.join(delimiter);
  const body = rows.map((row) =>
    columns
      .map((column) => {
        const raw = row[column];
        const text = raw == null ? "" : String(raw);
        if (text.includes(delimiter) || text.includes('"') || text.includes("\n")) {
          return `"${text.replace(/"/g, '""')}"`;
        }
        return text;
      })
      .join(delimiter)
  );
  return [header, ...body].join("\n");
}

function formatValue(value: unknown) {
  if (value == null) return "";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(4);
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
