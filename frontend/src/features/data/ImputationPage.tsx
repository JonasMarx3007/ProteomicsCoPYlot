import { useEffect, useMemo, useState } from "react";
import { buildPlotUrl, downloadImputationCsv, runImputation } from "../../lib/api";
import type { AnnotationKind, ImputationResultResponse } from "../../lib/types";

export default function ImputationPage() {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [qValue, setQValue] = useState(0.01);
  const [adjustStd, setAdjustStd] = useState(1);
  const [seed, setSeed] = useState(1337);
  const [sampleWise, setSampleWise] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImputationResultResponse | null>(null);
  const [downloadingCsv, setDownloadingCsv] = useState(false);

  async function fetchPreview() {
    try {
      setLoading(true);
      setError(null);
      const response = await runImputation({
        kind,
        qValue,
        adjustStd,
        seed,
        sampleWise,
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Imputation failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleRun() {
    await fetchPreview();
  }

  useEffect(() => {
    fetchPreview();
  }, [kind, qValue, adjustStd, seed, sampleWise]);

  const plotParams = useMemo(
    () => ({
      qValue,
      adjustStd,
      seed,
      sampleWise,
    }),
    [qValue, adjustStd, seed, sampleWise]
  );

  const beforePlotUrl = buildPlotUrl(`/api/plots/imputation/${kind}/before-missing.png`, plotParams);
  const overallPlotUrl = buildPlotUrl(`/api/plots/imputation/${kind}/overall-fit.png`, plotParams);
  const afterPlotUrl = buildPlotUrl(`/api/plots/imputation/${kind}/after-imputation.png`, plotParams);

  async function handleDownloadImputedCsv() {
    try {
      setDownloadingCsv(true);
      const blob = await downloadImputationCsv({
        kind,
        qValue,
        adjustStd,
        seed,
        sampleWise,
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `imputed_${kind}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download imputed CSV");
    } finally {
      setDownloadingCsv(false);
    }
  }

  const previewCsvUrl = useMemo(() => {
    if (!result || result.preview.length === 0) return null;
    const csv = rowsToCsv(result.preview);
    return `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`;
  }, [result]);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Impute Data</h2>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <SelectField
            label="Dataset level"
            value={kind}
            onChange={(value) => setKind(value as AnnotationKind)}
            options={[
              { value: "protein", label: "Protein" },
              { value: "phospho", label: "Phospho" },
            ]}
          />
          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <label className="inline-flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={sampleWise}
                onChange={(e) => setSampleWise(e.target.checked)}
              />
              Sample-wise imputation
            </label>
          </div>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <NumberField label="q-Value" value={qValue} onChange={setQValue} step={0.001} />
          <NumberField
            label="Adjust standard deviation"
            value={adjustStd}
            onChange={setAdjustStd}
            step={0.1}
          />
          <NumberField
            label="Random seed"
            value={seed}
            onChange={(value) => setSeed(Math.round(value))}
          />
        </div>

        <div className="mt-5">
          <button
            type="button"
            onClick={handleRun}
            disabled={loading}
            className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Updating..." : "Impute Data Values"}
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
            <h3 className="text-lg font-semibold text-slate-900">Summary</h3>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <SummaryCard label="Rows" value={String(result.rows)} />
              <SummaryCard label="Missing Before" value={String(result.missingBefore)} />
              <SummaryCard label="Missing After" value={String(result.missingAfter)} />
              <SummaryCard
                label="Imputation Quantile"
                value={result.quantile == null ? "n/a" : result.quantile.toFixed(4)}
              />
            </div>
            {result.warnings.length > 0 ? (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {result.warnings.join(" ")}
              </div>
            ) : null}
          </section>

          <PlotSection
            title="Before: With vs Without Missing Values"
            imageUrl={beforePlotUrl}
            filename={`imputation_before_${kind}.png`}
          />

          <PlotSection
            title="Overall Distribution with Normal Fit"
            imageUrl={overallPlotUrl}
            filename={`imputation_fit_${kind}.png`}
          />

          <PlotSection
            title="After: Non-Imputed vs Imputed Values"
            imageUrl={afterPlotUrl}
            filename={`imputation_after_${kind}.png`}
          />

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-slate-900">Imputed Data (Preview)</h3>
              <div className="flex flex-wrap gap-2">
                {previewCsvUrl ? (
                  <a
                    href={previewCsvUrl}
                    download={`imputed_preview_${kind}.csv`}
                    className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
                  >
                    Download Preview CSV
                  </a>
                ) : null}
                <button
                  type="button"
                  onClick={handleDownloadImputedCsv}
                  disabled={downloadingCsv}
                  className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {downloadingCsv ? "Downloading..." : "Download Full Imputed CSV"}
                </button>
              </div>
            </div>
            <div className="mt-4">
              <PreviewTable rows={result.preview} emptyText="No imputed rows available." />
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function PlotSection({
  title,
  imageUrl,
  filename,
}: {
  title: string;
  imageUrl: string;
  filename: string;
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <a
          href={imageUrl}
          download={filename}
          className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
        >
          Download Plot
        </a>
      </div>
      <div className="mt-4">
        <img src={imageUrl} alt={title} className="w-full rounded-xl border border-slate-200" />
      </div>
    </section>
  );
}

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step = 1,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input
        type="number"
        value={value}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
      />
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
  rows,
  emptyText,
}: {
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
  );
}

function rowsToCsv(rows: Record<string, unknown>[]): string {
  if (rows.length === 0) return "";
  const columns = Array.from(
    rows.reduce((acc, row) => {
      Object.keys(row).forEach((key) => acc.add(key));
      return acc;
    }, new Set<string>())
  );

  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const lines = [
    columns.join(","),
    ...rows.map((row) => columns.map((column) => escape(row[column])).join(",")),
  ];
  return lines.join("\n");
}
