import { useEffect, useState } from "react";
import { buildPlotUrl, getDistributionSummary } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import type { AnnotationKind, DistributionSummaryResponse } from "../../lib/types";

export default function DistributionPage() {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const { availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<DistributionSummaryResponse | null>(null);

  async function loadSummary() {
    if (!availableKinds.includes(kind)) {
      setSummary(null);
      setError("Please upload a protein, phospho, or phosphoprotein dataset first.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const data = await getDistributionSummary(kind);
      setSummary(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load distribution summary");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (availableKinds.length === 0) {
      setSummary(null);
      return;
    }
    if (!availableKinds.includes(kind)) {
      setKind(availableKinds[0]);
      return;
    }
    loadSummary();
  }, [kind, availableKinds]);

  const qqPlotUrl = buildPlotUrl(`/api/plots/distribution/${kind}/qqnorm.png`);
  const qqReferenceImageUrl = "/assets/qqnorm.jpg";
  const qqReferenceTextUrl = "/assets/qqnorm_txt.jpg";

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Distribution</h2>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <SelectField
            label="Dataset level"
            value={kindOptions.length === 0 ? "" : kind}
            onChange={(value) => setKind(value as AnnotationKind)}
            options={kindOptions}
          />
          <div className="self-end">
            <button
              type="button"
              onClick={loadSummary}
              disabled={loading}
              className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "Refreshing..." : "Refresh"}
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
      </section>

      {kindOptions.length === 0 ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
          Upload a protein, phospho, or phosphoprotein dataset in the Data tab to enable distribution plots.
        </section>
      ) : null}

      {kindOptions.length > 0 && summary ? (
        <>
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-slate-900">QQ Norm Plot</h3>
              <a
                href={qqPlotUrl}
                download={`qqnorm_${kind}.png`}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download Plot
              </a>
            </div>
            {summary.warnings.length > 0 ? (
              <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {summary.warnings.join(" ")}
              </div>
            ) : null}
            <div className="mt-4">
              <img src={qqPlotUrl} alt="QQ norm plot" className="w-full rounded-xl border border-slate-200" />
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">QQ Norm Reference</h3>
            <div className="mt-4 grid gap-4 grid-cols-1">
              <img
                src={qqReferenceImageUrl}
                alt="QQ norm reference"
                className="w-full rounded-xl border border-slate-200"
              />
              <img
                src={qqReferenceTextUrl}
                alt="QQ norm reference text"
                className="w-full rounded-xl border border-slate-200"
              />
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
