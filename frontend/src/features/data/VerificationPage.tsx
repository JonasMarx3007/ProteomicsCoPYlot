import { useEffect, useState } from "react";
import { buildPlotUrl, getVerificationSummary } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import type { AnnotationKind, VerificationSummaryResponse } from "../../lib/types";

export default function VerificationPage() {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const { availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<VerificationSummaryResponse | null>(null);

  async function loadSummary() {
    if (!availableKinds.includes(kind)) {
      setSummary(null);
      setError("Please upload a protein or phospho dataset first.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const data = await getVerificationSummary(kind);
      setSummary(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load verification summary");
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

  const firstDigitUrl = buildPlotUrl(`/api/plots/verification/${kind}/first-digit.png`);
  const duplicateUrl = buildPlotUrl(`/api/plots/verification/${kind}/duplicate-pattern.png`);

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Verification</h2>

        <div className="mt-4 grid gap-4 lg:grid-cols-3">
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
          Upload a protein or phospho dataset in the Data tab to enable verification plots.
        </section>
      ) : null}

      {kindOptions.length > 0 && summary ? (
        <>
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-slate-900">First-Digit Analysis</h3>
              <a
                href={firstDigitUrl}
                download={`verification_first_digit_${kind}.png`}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download Plot
              </a>
            </div>
            <div className="mt-4">
              <img src={firstDigitUrl} alt="First digit verification plot" className="w-full rounded-xl border border-slate-200" />
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-slate-900">Duplicate Pattern Structure</h3>
              <a
                href={duplicateUrl}
                download={`verification_duplicate_${kind}.png`}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download Plot
              </a>
            </div>
            <div className="mt-4">
              <img src={duplicateUrl} alt="Duplicate pattern verification plot" className="w-full rounded-xl border border-slate-200" />
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
