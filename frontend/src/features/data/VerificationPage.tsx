import { useEffect, useState } from "react";
import { buildPlotUrl, getVerificationSummary } from "../../lib/api";
import type { AnnotationKind, VerificationSummaryResponse } from "../../lib/types";

export default function VerificationPage() {
  const [kind, setKind] = useState<AnnotationKind>("protein");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<VerificationSummaryResponse | null>(null);

  async function loadSummary() {
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
    loadSummary();
  }, [kind]);

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
              value={kind}
              onChange={(e) => setKind(e.target.value as AnnotationKind)}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
            >
              <option value="protein">Protein</option>
              <option value="phospho">Phospho</option>
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

      {summary ? (
        <>
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">First-Digit Analysis</h3>
            <div className="mt-4">
              <img src={firstDigitUrl} alt="First digit verification plot" className="w-full rounded-xl border border-slate-200" />
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">Duplicate Pattern Structure</h3>
            <div className="mt-4">
              <img src={duplicateUrl} alt="Duplicate pattern verification plot" className="w-full rounded-xl border border-slate-200" />
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}
