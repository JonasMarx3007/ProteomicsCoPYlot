import { useEffect, useMemo, useState } from "react";
import { downloadIdTranslation, getCurrentDatasets, runIdTranslation } from "../../lib/api";
import type {
  AnnotationKind,
  CurrentDatasetsResponse,
  IdTranslationResponse,
} from "../../lib/types";

const DEFAULT_DATABASES = [
  "HGNC ID",
  "HGNC Symbol",
  "HGNC Name",
  "HGNC Alias Symbol",
  "Ensembl",
  "VEGA",
  "ENA",
  "RefSeq",
  "CCDS",
  "PubMed",
  "Enzyme Commission (EC)",
  "RNAcentral",
  "UniProt Accession",
  "UniProt Name",
  "UniProt Gene",
  "UniProt Description",
  "UniProt Secondary Accession",
  "UniProt All Accessions",
];

export default function IdTranslatorPage() {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [datasets, setDatasets] = useState<CurrentDatasetsResponse | null>(null);
  const [column, setColumn] = useState("");
  const [inputDb, setInputDb] = useState("HGNC Symbol");
  const [outputDb, setOutputDb] = useState("HGNC Symbol");
  const [autoDetectInput, setAutoDetectInput] = useState(true);
  const [result, setResult] = useState<IdTranslationResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const activeDataset = datasets?.[kind] ?? null;
  const kindOptions = useMemo(() => {
    const options: { value: AnnotationKind; label: string }[] = [];
    if (datasets?.protein) options.push({ value: "protein", label: "Protein" });
    if (datasets?.phospho) options.push({ value: "phospho", label: "Phospho" });
    return options;
  }, [datasets]);
  const columns = activeDataset?.columnNames ?? [];
  const databaseOptions = result?.availableDatabases ?? DEFAULT_DATABASES;

  useEffect(() => {
    getCurrentDatasets()
      .then(setDatasets)
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load datasets");
      });
  }, []);

  useEffect(() => {
    if (kindOptions.length === 0) {
      setResult(null);
      return;
    }
    if (!kindOptions.some((option) => option.value === kind)) {
      setKind(kindOptions[0].value);
    }
  }, [kindOptions, kind]);

  useEffect(() => {
    setColumn((current) => {
      if (columns.includes(current)) return current;
      return columns[0] ?? "";
    });
  }, [kind, columns]);

  useEffect(() => {
    setResult(null);
    setError(null);
  }, [kind]);

  const canRun = Boolean(activeDataset && column && outputDb && (autoDetectInput || inputDb));

  const requestPayload = useMemo(
    () => ({
      kind,
      column,
      inputDb: autoDetectInput ? null : inputDb,
      outputDb,
      autoDetectInput,
    }),
    [autoDetectInput, column, inputDb, kind, outputDb]
  );

  async function handleTranslate() {
    if (!canRun) return;
    try {
      setLoading(true);
      setError(null);
      const response = await runIdTranslation(requestPayload);
      setResult(response);
      setInputDb(response.inputDb);
      try {
        const current = await getCurrentDatasets();
        setDatasets(current);
      } catch {
        // Keep translation preview/result even if dataset snapshot refresh fails transiently.
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to translate IDs");
    } finally {
      setLoading(false);
    }
  }

  async function handleDownload() {
    try {
      setDownloading(true);
      setError(null);
      const blob = await downloadIdTranslation(requestPayload);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = result?.downloadFilename ?? `translated_${kind}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download translated table");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">ID Translator</h2>
        <p className="mt-2 text-sm text-slate-600">
          Translate identifiers in a loaded protein or phospho table, append mapped values as new column(s), and write
          the result back to the active dataset for downstream annotation.
        </p>

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <SelectField
            label="Dataset level"
            value={kind}
            onChange={(value) => setKind(value as AnnotationKind)}
            options={kindOptions}
            disabled={kindOptions.length === 0}
          />
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <div className="font-medium text-slate-700">Current dataset</div>
            {activeDataset ? (
              <div className="mt-2 space-y-1 text-slate-600">
                <div className="truncate" title={activeDataset.filename}>
                  {activeDataset.filename}
                </div>
                <div>
                  {activeDataset.rows} rows, {activeDataset.columns} columns
                </div>
              </div>
            ) : (
              <div className="mt-2 text-slate-500">No dataset loaded.</div>
            )}
          </div>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <SelectField
            label="Column to translate"
            value={column}
            onChange={setColumn}
            options={columns.map((value) => ({ value, label: value }))}
            disabled={!columns.length}
          />
          <SelectField
            label="Translate to"
            value={outputDb}
            onChange={setOutputDb}
            options={databaseOptions.map((value) => ({ value, label: value }))}
          />
          <SelectField
            label="Translate from"
            value={inputDb}
            onChange={setInputDb}
            options={databaseOptions.map((value) => ({ value, label: value }))}
            disabled={autoDetectInput}
          />
        </div>

        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <label className="inline-flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={autoDetectInput}
              onChange={(e) => setAutoDetectInput(e.target.checked)}
            />
            Auto-detect input database from the selected column
          </label>
        </div>

        <div className="mt-5 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={handleTranslate}
            disabled={!canRun || loading}
            className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Translating..." : "Translate and Preview"}
          </button>
          <button
            type="button"
            onClick={handleDownload}
            disabled={!result || downloading}
            className="rounded-xl border border-slate-300 bg-white px-5 py-2.5 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {downloading ? "Downloading..." : "Download Translated Table"}
          </button>
        </div>

        {error ? (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        ) : null}
      </section>

      {kindOptions.length === 0 ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
          Upload a protein or phospho dataset in the Data tab to enable ID translation.
        </section>
      ) : null}

      {kindOptions.length > 0 && result ? (
        <>
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">Translation Summary</h3>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <SummaryCard label="Input DB" value={result.inputDb} />
              <SummaryCard label="Output DB" value={result.outputDb} />
              <SummaryCard label="Translated Rows" value={`${result.translatedCount}/${result.totalRows}`} />
              <SummaryCard label="Appended Column" value={result.outputColumn} />
            </div>
            {result.warnings.length > 0 ? (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {result.warnings.join(" ")}
              </div>
            ) : null}
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-slate-900">Preview</h3>
              <div className="text-sm text-slate-500">Showing first 50 rows</div>
            </div>
            <div className="mt-4">
              <PreviewTable rows={result.preview} emptyText="No translated rows available." />
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled || options.length === 0}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
      >
        {options.length === 0 ? <option value="">No options available</option> : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
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
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
        {emptyText}
      </div>
    );
  }

  const columns = Array.from(
    rows.reduce((set, row) => {
      Object.keys(row).forEach((key) => set.add(key));
      return set;
    }, new Set<string>())
  );

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200">
      <div className="max-h-[34rem] overflow-auto">
        <table className="min-w-full divide-y divide-slate-200 text-left text-sm">
          <thead className="sticky top-0 bg-slate-50">
            <tr>
              {columns.map((columnName) => (
                <th key={columnName} className="px-4 py-3 font-medium text-slate-700">
                  {columnName}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 bg-white">
            {rows.map((row, index) => (
              <tr key={index}>
                {columns.map((columnName) => (
                  <td key={columnName} className="max-w-xs px-4 py-3 align-top text-slate-600">
                    {String(row[columnName] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
