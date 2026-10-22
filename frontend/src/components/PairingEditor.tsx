import { useEffect, useMemo, useState } from "react";
import { updateAnnotationPairing } from "../lib/api";
import { IS_VIEWER_MODE } from "../lib/appMode";
import type { AnnotationKind, SamplePairAssignment } from "../lib/types";

type Props = {
  kind: AnnotationKind;
  condition1: string;
  condition2: string;
  samplesByCondition: Record<string, string[]>;
  pairIdsBySample: Record<string, string>;
  onSaved?: () => void | Promise<void>;
};

function selectionFromMetadata(
  leftSamples: string[],
  rightSamples: string[],
  pairIdsBySample: Record<string, string>
) {
  const rightByPair = new Map<string, string>();
  rightSamples.forEach((sample) => {
    const pairId = pairIdsBySample[sample];
    if (pairId) rightByPair.set(pairId, sample);
  });
  return leftSamples.map((sample) => rightByPair.get(pairIdsBySample[sample]) ?? "");
}

function selectionSignature(leftSamples: string[], selectedRight: string[]) {
  return leftSamples.map((sample, index) => `${sample}\u0000${selectedRight[index] ?? ""}`).join("\u0001");
}

function usablePairing(
  rightSamples: string[],
  selectedRight: string[]
) {
  const pairedSamples = selectedRight.filter(Boolean);
  return (
    pairedSamples.length >= 2 &&
    new Set(pairedSamples).size === pairedSamples.length &&
    pairedSamples.every((sample) => rightSamples.includes(sample))
  );
}

export default function PairingEditor({
  kind,
  condition1,
  condition2,
  samplesByCondition,
  pairIdsBySample,
  onSaved,
}: Props) {
  const leftSamples = useMemo(
    () => samplesByCondition[condition1] ?? [],
    [condition1, samplesByCondition]
  );
  const rightSamples = useMemo(
    () => samplesByCondition[condition2] ?? [],
    [condition2, samplesByCondition]
  );
  const metadataSelection = useMemo(
    () => selectionFromMetadata(leftSamples, rightSamples, pairIdsBySample),
    [leftSamples, rightSamples, pairIdsBySample]
  );
  const metadataSignature = useMemo(
    () =>
      usablePairing(rightSamples, metadataSelection)
        ? selectionSignature(leftSamples, metadataSelection)
        : "",
    [leftSamples, rightSamples, metadataSelection]
  );
  const [selectedRight, setSelectedRight] = useState(metadataSelection);
  const [savedSignature, setSavedSignature] = useState(metadataSignature);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSelectedRight(metadataSelection);
    setSavedSignature(metadataSignature);
    setMessage(null);
    setError(null);
  }, [condition1, condition2, metadataSelection, metadataSignature]);

  const differentConditions = condition1 && condition2 && condition1 !== condition2;
  const valid = Boolean(differentConditions) && usablePairing(rightSamples, selectedRight);
  const currentSignature = selectionSignature(leftSamples, selectedRight);
  const ready = valid && currentSignature === savedSignature;

  function chooseRight(index: number, sample: string) {
    setSelectedRight((current) => {
      const next = [...current];
      next[index] = sample;
      return next;
    });
    setMessage(null);
    setError(null);
  }

  async function save() {
    if (!valid || IS_VIEWER_MODE) return;
    const pairs: SamplePairAssignment[] = leftSamples.flatMap((sample, index) => {
      const partner = selectedRight[index];
      return partner ? [{ condition1Sample: sample, condition2Sample: partner }] : [];
    });
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      await updateAnnotationPairing({ kind, condition1, condition2, pairs });
      setMessage(`${pairs.length} sample pairs saved.`);
      if (onSaved) {
        try {
          await onSaved();
        } catch {
          setError("Pairing was saved, but the page could not refresh. Save again to retry.");
          return;
        }
      }
      setSavedSignature(currentSignature);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to save sample pairing");
    } finally {
      setSaving(false);
    }
  }

  const chosenCount = selectedRight.filter(Boolean).length;
  const excludedLeft = leftSamples.length - chosenCount;
  const excludedRight = rightSamples.length - chosenCount;
  const excludedCount = excludedLeft + excludedRight;
  // Other conditions that share a pair ID with a sample here: those links are
  // kept by a save, and an edit that would break one is refused by the backend.
  const linkedConditions = useMemo(() => {
    const here = new Set([...leftSamples, ...rightSamples]);
    const ids = new Set([...here].map((sample) => pairIdsBySample[sample]).filter(Boolean));
    return Object.entries(samplesByCondition)
      .filter(([condition, samples]) =>
        condition !== condition1 && condition !== condition2 &&
        samples.some((sample) => ids.has(pairIdsBySample[sample])))
      .map(([condition]) => condition);
  }, [leftSamples, rightSamples, pairIdsBySample, samplesByCondition, condition1, condition2]);

  return (
    <div className="mt-4 overflow-hidden rounded-2xl border border-indigo-200 bg-indigo-50/60">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-indigo-200 px-4 py-3">
        <div>
          <h4 className="font-semibold text-slate-900">Pair samples</h4>
          <p className="mt-1 text-sm text-slate-600">
            Match each sample from {condition1 || "Condition 1"} to its corresponding sample in{" "}
            {condition2 || "Condition 2"}. Samples left without a partner are excluded from this
            paired comparison.
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Saving updates the active metadata pairing used by every paired analysis module.
          </p>
          {linkedConditions.length > 0 ? (
            <p className="mt-1 text-xs text-amber-700">
              Some samples here share pair IDs with {linkedConditions.join(", ")}. Those links are
              kept; a change that would break one is refused.
            </p>
          ) : null}
        </div>
        <span
          className={`rounded-full px-3 py-1 text-xs font-medium ${
            ready
              ? "bg-emerald-100 text-emerald-800"
              : "bg-white text-indigo-800 ring-1 ring-indigo-200"
          }`}
        >
          {ready ? `${chosenCount} pairs ready` : `${chosenCount} pairs selected`}
        </span>
      </div>

      {!differentConditions ? (
        <p className="px-4 py-4 text-sm text-amber-800">
          Select two different conditions before pairing samples.
        </p>
      ) : leftSamples.length < 2 || rightSamples.length < 2 ? (
        <p className="px-4 py-4 text-sm text-amber-800">
          Paired analysis requires at least two samples in each condition.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-[minmax(0,1fr)_2.5rem_minmax(0,1fr)] gap-2 bg-white/70 px-4 py-2 text-xs font-medium uppercase tracking-wide text-slate-500">
            <span>{condition1}</span>
            <span aria-hidden="true" />
            <span>{condition2}</span>
          </div>
          <div className="divide-y divide-indigo-100">
            {leftSamples.map((leftSample, index) => {
              const currentRight = selectedRight[index] ?? "";
              const usedByOtherRow = new Set(
                selectedRight.filter((sample, selectedIndex) => selectedIndex !== index && sample)
              );
              return (
                <div
                  key={leftSample}
                  className="grid grid-cols-[minmax(0,1fr)_2.5rem_minmax(0,1fr)] items-center gap-2 px-4 py-3"
                >
                  <div className="min-w-0 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800">
                    <span className="block truncate" title={leftSample}>
                      {leftSample}
                    </span>
                  </div>
                  <span className="text-center text-lg text-indigo-500" aria-hidden="true">
                    {"\u2194"}
                  </span>
                  <select
                    value={currentRight}
                    onChange={(event) => chooseRight(index, event.target.value)}
                    disabled={IS_VIEWER_MODE}
                    aria-label={`Sample paired with ${leftSample}`}
                    className="min-w-0 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 outline-none focus:border-indigo-500 disabled:bg-slate-100"
                  >
                    <option value="">Leave unpaired (excluded)</option>
                    {rightSamples.map((rightSample) => (
                      <option
                        key={rightSample}
                        value={rightSample}
                        disabled={usedByOtherRow.has(rightSample)}
                      >
                        {rightSample}
                      </option>
                    ))}
                  </select>
                </div>
              );
            })}
          </div>
          <div className="border-t border-indigo-100 bg-white/50 px-4 py-2 text-sm text-slate-600">
            {excludedCount > 0
              ? `${excludedCount} sample${excludedCount === 1 ? "" : "s"} excluded from this comparison (${excludedLeft} from ${condition1}, ${excludedRight} from ${condition2}).`
              : "All samples are included in this paired comparison."}
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-indigo-200 px-4 py-3">
            {IS_VIEWER_MODE ? (
              <p className="text-sm text-slate-600">Pairing is read-only in viewer mode.</p>
            ) : (
              <>
                <button
                  type="button"
                  onClick={save}
                  disabled={!valid || ready || saving}
                  className="rounded-xl bg-indigo-700 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-600 disabled:cursor-not-allowed disabled:bg-slate-400"
                >
                  {saving ? "Saving..." : ready ? "Pairing saved" : "Save pairing"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedRight(leftSamples.map(() => ""));
                    setMessage(null);
                    setError(null);
                  }}
                  disabled={saving}
                  className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:opacity-50"
                >
                  Clear choices
                </button>
              </>
            )}
            {!ready && valid ? (
              <span className="text-sm text-amber-700">Save this mapping before running the plot.</span>
            ) : !valid ? (
              <span className="text-sm text-amber-700">
                Select at least two sample pairs to run a paired analysis.
              </span>
            ) : null}
            {message ? <span className="text-sm text-emerald-700">{message}</span> : null}
            {error ? <span className="text-sm text-red-700">{error}</span> : null}
          </div>
        </>
      )}
    </div>
  );
}
