import { useEffect, useState } from "react";
import { buildPlotUrl, runImputation } from "../../lib/api";
import type {
  AnnotationKind,
  ImputationResultResponse,
} from "../../lib/types";

export default function ImputationPage() {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [qValue, setQValue] = useState(0.01);
  const [adjustStd, setAdjustStd] = useState(1);
  const [seed, setSeed] = useState(1337);
  const [sampleWise, setSampleWise] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImputationResultResponse | null>(null);

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

  const plotParams = {
    qValue,
    adjustStd,
    seed,
    sampleWise,
  };

  const beforePlotUrl = buildPlotUrl(`/api/plots/imputation/${kind}/before-missing.png`, plotParams);
  const overallPlotUrl = buildPlotUrl(`/api/plots/imputation/${kind}/overall-fit.png`, plotParams);
  const afterPlotUrl = buildPlotUrl(`/api/plots/imputation/${kind}/after-imputation.png`, plotParams);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Impute Data</h2>

        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <SelectField
            label="Dataset level"
            value={kind}
            onChange={(value) => setKind(value as AnnotationKind)}
            options={[
              { value: "protein", label: "Protein" },
              { value: "phospho", label: "Phospho" },
            ]}
          />
          <NumberField
            label="Random seed"
            value={seed}
            onChange={(value) => setSeed(Math.round(value))}
          />
          <NumberField label="q-Value" value={qValue} onChange={setQValue} step={0.001} />
          <NumberField
            label="Adjust standard deviation"
            value={adjustStd}
            onChange={setAdjustStd}
            step={0.1}
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
            <div className="mt-3 text-sm text-slate-600">
              Source used automatically: <span className="font-medium">{result.sourceUsed}</span>
            </div>
            {result.warnings.length > 0 ? (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {result.warnings.join(" ")}
              </div>
            ) : null}
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">
              Before: With vs Without Missing Values
            </h3>
            <div className="mt-4">
              <img src={beforePlotUrl} alt="Before imputation plot" className="w-full rounded-xl border border-slate-200" />
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">
              Overall Distribution with Normal Fit
            </h3>
            <div className="mt-4">
              <img src={overallPlotUrl} alt="Overall distribution and normal fit plot" className="w-full rounded-xl border border-slate-200" />
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">
              After: Non-Imputed vs Imputed Values
            </h3>
            <div className="mt-4">
              <img src={afterPlotUrl} alt="After imputation plot" className="w-full rounded-xl border border-slate-200" />
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
