import { useEffect, useMemo, useState } from "react";
import {
  clearUploadedAnnotationMetadata,
  generateAnnotation,
  getCurrentAnnotation,
  getCurrentDatasets,
  getUploadedAnnotationMetadata,
  uploadAnnotationMetadata,
} from "../../lib/api";
import type {
  AnnotationFilterConfig,
  AnnotationKind,
  AnnotationResultResponse,
  ConditionAssignment,
  CurrentDatasetsResponse,
  MetadataUploadResponse,
} from "../../lib/types";

type ConditionDraft = {
  id: number;
  name: string;
  columns: string[];
};

const DEFAULT_FILTER: AnnotationFilterConfig = {
  minPresent: 0,
  mode: "per_group",
};

export default function AnnotationPage() {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [currentDatasets, setCurrentDatasets] = useState<CurrentDatasetsResponse | null>(
    null
  );
  const [conditions, setConditions] = useState<ConditionDraft[]>([
    { id: 1, name: "", columns: [] },
  ]);
  const [isLog2Transformed, setIsLog2Transformed] = useState(true);
  const [filterConfig, setFilterConfig] = useState<AnnotationFilterConfig>(DEFAULT_FILTER);
  const [result, setResult] = useState<AnnotationResultResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metadataFile, setMetadataFile] = useState<File | null>(null);
  const [uploadedMetadata, setUploadedMetadata] = useState<MetadataUploadResponse | null>(null);
  const [uploadingMetadata, setUploadingMetadata] = useState(false);
  const [clearingMetadata, setClearingMetadata] = useState(false);

  const activeDataset = currentDatasets?.[kind] ?? null;
  const availableColumns = activeDataset?.columnNames ?? [];
  const availableKinds = useMemo<AnnotationKind[]>(() => {
    const kinds: AnnotationKind[] = [];
    if (currentDatasets?.protein) kinds.push("protein");
    if (currentDatasets?.phospho) kinds.push("phospho");
    return kinds;
  }, [currentDatasets]);
  const kindOptions = useMemo(
    () =>
      availableKinds.map((value) => ({
        value,
        label: value === "protein" ? "Protein" : "Phospho",
      })),
    [availableKinds]
  );

  useEffect(() => {
    getCurrentDatasets()
      .then(setCurrentDatasets)
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load datasets");
      });
  }, []);

  useEffect(() => {
    if (availableKinds.length === 0) return;
    if (!availableKinds.includes(kind)) {
      setKind(availableKinds[0]);
    }
  }, [availableKinds, kind]);

  useEffect(() => {
    getCurrentAnnotation(kind)
      .then((stored) => {
        setResult(stored);
        setIsLog2Transformed(stored.isLog2Transformed);
        if (stored.filter) {
          setFilterConfig(stored.filter);
        }
      })
      .catch(() => {
        setResult(null);
      });
  }, [kind]);

  useEffect(() => {
    getUploadedAnnotationMetadata(kind)
      .then((metadata) => setUploadedMetadata(metadata))
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load uploaded metadata");
      });
  }, [kind]);

  function addCondition() {
    setConditions((prev) => [
      ...prev,
      { id: Date.now(), name: "", columns: [] },
    ]);
  }

  function removeCondition(id: number) {
    setConditions((prev) => prev.filter((condition) => condition.id !== id));
  }

  function updateConditionName(id: number, name: string) {
    setConditions((prev) =>
      prev.map((condition) =>
        condition.id === id ? { ...condition, name } : condition
      )
    );
  }

  function updateConditionColumns(id: number, columns: string[]) {
    setConditions((prev) =>
      prev.map((condition) =>
        condition.id === id ? { ...condition, columns } : condition
      )
    );
  }

  const requestConditions = useMemo<ConditionAssignment[]>(() => {
    return conditions
      .map((condition) => ({
        name: condition.name.trim(),
        columns: condition.columns,
      }))
      .filter((condition) => condition.name.length > 0 && condition.columns.length > 0);
  }, [conditions]);

  async function handleGenerate() {
    if (!activeDataset) {
      setError(`No ${kind} dataset loaded. Upload data first.`);
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const generated = await generateAnnotation({
        kind,
        conditions: requestConditions,
        isLog2Transformed,
        filter: filterConfig,
      });

      setResult(generated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate annotation");
    } finally {
      setLoading(false);
    }
  }

  async function handleMetadataUpload() {
    if (!activeDataset) {
      setError(`No ${kind} dataset loaded. Upload data first.`);
      return;
    }
    if (!metadataFile) {
      setError("Please choose a metadata file first.");
      return;
    }

    try {
      setUploadingMetadata(true);
      setError(null);
      const uploaded = await uploadAnnotationMetadata(metadataFile, kind);
      setUploadedMetadata(uploaded);
      setMetadataFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload metadata");
    } finally {
      setUploadingMetadata(false);
    }
  }

  async function handleClearUploadedMetadata() {
    try {
      setClearingMetadata(true);
      setError(null);
      await clearUploadedAnnotationMetadata(kind);
      setUploadedMetadata(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to clear uploaded metadata");
    } finally {
      setClearingMetadata(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Data Annotation</h2>

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700">
              Dataset level
            </label>
            <select
              value={kindOptions.length === 0 ? "" : kind}
              onChange={(e) => setKind(e.target.value as AnnotationKind)}
              disabled={kindOptions.length === 0}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
            >
              {kindOptions.length === 0 ? (
                <option value="">No dataset available</option>
              ) : (
                kindOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))
              )}
            </select>
          </div>

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

        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
          <label className="inline-flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={isLog2Transformed}
              onChange={(e) => setIsLog2Transformed(e.target.checked)}
            />
            Dataset is already log2 transformed
          </label>
        </div>

        {kindOptions.length === 0 ? (
          <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
            Upload a protein or phospho dataset in the Data tab before uploading metadata.
          </div>
        ) : null}

        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-sm font-medium text-slate-700">Uploaded Metadata (Optional)</div>
          <p className="mt-1 text-sm text-slate-600">
            If a metadata file is uploaded for this level, it overrides UI condition mapping during annotation generation.
          </p>
          <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto_auto] lg:items-end">
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">Metadata file</label>
              <input
                type="file"
                accept=".csv,.tsv,.txt,.xlsx,.parquet"
                onChange={(e) => setMetadataFile(e.target.files?.[0] ?? null)}
                disabled={!activeDataset}
                className="block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:bg-slate-100"
              />
            </div>
            <button
              type="button"
              onClick={handleMetadataUpload}
              disabled={!activeDataset || !metadataFile || uploadingMetadata}
              className="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {uploadingMetadata ? "Uploading..." : "Upload Metadata"}
            </button>
            <button
              type="button"
              onClick={handleClearUploadedMetadata}
              disabled={!activeDataset || !uploadedMetadata || clearingMetadata}
              className="rounded-xl border border-slate-300 bg-white px-4 py-2.5 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {clearingMetadata ? "Clearing..." : "Clear Uploaded Metadata"}
            </button>
          </div>

          {uploadedMetadata ? (
            <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
              Using uploaded metadata file: {uploadedMetadata.filename} ({uploadedMetadata.rows} rows)
            </div>
          ) : (
            <div className="mt-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
              No uploaded metadata for this dataset level.
            </div>
          )}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-900">Condition Mapping</h3>
          <button
            type="button"
            onClick={addCondition}
            className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
          >
            Add condition
          </button>
        </div>

        <div className="mt-4 space-y-4">
          {conditions.map((condition) => (
            <div key={condition.id} className="rounded-xl border border-slate-200 p-4">
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]">
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700">
                    Condition name
                  </label>
                  <input
                    type="text"
                    value={condition.name}
                    onChange={(e) => updateConditionName(condition.id, e.target.value)}
                    placeholder="Control"
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900"
                  />
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700">
                    Sample columns
                  </label>
                  <select
                    multiple
                    value={condition.columns}
                    size={Math.max(4, Math.min(10, availableColumns.length || 4))}
                    onChange={(e) =>
                      updateConditionColumns(
                        condition.id,
                        Array.from(e.target.selectedOptions).map((option) => option.value)
                      )
                    }
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900"
                  >
                    {availableColumns.map((column) => (
                      <option key={column} value={column}>
                        {column}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="self-end">
                  <button
                    type="button"
                    onClick={() => removeCondition(condition.id)}
                    className="rounded-xl border border-red-300 bg-white px-3 py-2 text-sm text-red-700 transition hover:bg-red-50"
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Filter Settings</h3>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700">
              Keep rows with at least N values
            </label>
            <input
              type="number"
              min={0}
              value={filterConfig.minPresent}
              onChange={(e) =>
                setFilterConfig((prev) => ({
                  ...prev,
                  minPresent: Number(e.target.value) || 0,
                }))
              }
              className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900"
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700">
              Filter mode
            </label>
            <select
              value={filterConfig.mode}
              onChange={(e) =>
                setFilterConfig((prev) => ({
                  ...prev,
                  mode: e.target.value as AnnotationFilterConfig["mode"],
                }))
              }
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
            >
              <option value="per_group">Per group</option>
              <option value="in_at_least_one_group">In at least one group</option>
            </select>
          </div>
        </div>

        <div className="mt-5">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={!activeDataset || loading}
            className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Generating..." : "Generate Annotation"}
          </button>
        </div>

        {error && (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
      </section>

      {result ? (
        <>
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">Result Summary</h3>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <SummaryCard label="Source Rows" value={String(result.sourceRows)} />
              <SummaryCard label="Metadata Rows" value={String(result.metadataRows)} />
              <SummaryCard label="Conditions" value={String(result.conditionCount)} />
              <SummaryCard label="Filtered Rows" value={String(result.filteredRows)} />
              <SummaryCard label="Metadata Source" value={result.metadataSource} />
            </div>

            {result.warnings.length > 0 && (
              <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {result.warnings.join(" ")}
              </div>
            )}
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">Metadata Preview</h3>
            <div className="mt-4">
              <PreviewTable
                title="metadata_preview"
                rows={result.metadataPreview}
                emptyText="No metadata rows available."
              />
            </div>
          </section>

          {uploadedMetadata ? (
            <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-lg font-semibold text-slate-900">Uploaded Metadata Preview</h3>
              <div className="mt-4">
                <PreviewTable
                  title="uploaded_metadata_preview"
                  rows={uploadedMetadata.preview}
                  emptyText="No uploaded metadata preview available."
                />
              </div>
            </section>
          ) : null}

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">Filtered Data Preview</h3>
            <div className="mt-4">
              <PreviewTable
                title="filtered_data_preview"
                rows={result.filteredPreview}
                emptyText="No filtered rows available."
              />
            </div>
          </section>
        </>
      ) : (
        <section className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          No annotation result yet.
        </section>
      )}
    </div>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold text-slate-900">{value}</div>
    </div>
  );
}

function PreviewTable({
  title,
  rows,
  emptyText,
}: {
  title: string;
  rows: Record<string, unknown>[];
  emptyText: string;
}) {
  const columns = useMemo(() => {
    const seen = new Set<string>();
    rows.forEach((row) => {
      Object.keys(row).forEach((key) => seen.add(key));
    });
    return Array.from(seen);
  }, [rows]);

  if (rows.length === 0 || columns.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        {emptyText}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <a
        href={`data:text/csv;charset=utf-8,${encodeURIComponent(rowsToCsv(rows, columns))}`}
        download={`${title}.csv`}
        className="inline-flex rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
      >
        Download CSV
      </a>
      <div className="overflow-x-auto rounded-xl border border-slate-200">
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
    </div>
  );
}

function rowsToCsv(rows: Record<string, unknown>[], columns: string[]): string {
  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const lines = [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => escape(row[column])).join(",")),
  ];
  return lines.join("\n");
}
