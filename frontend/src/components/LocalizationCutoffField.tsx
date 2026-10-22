import { useEffect, useId, useState } from "react";
import { AssistantInput } from "./AssistantFields";
import { usePhosphoLocalizationCutoff } from "../lib/phosphoLocalization";

type Props = {
  /** Shown only for this dataset level; omit to always show (Phospho-specific module). */
  kind?: string;
  className?: string;
};

function formatCutoff(value: number) {
  return Number.isFinite(value) ? value.toFixed(2) : "0.00";
}

/**
 * The session-wide phosphosite localization probability cutoff.
 *
 * Every phosphosite plot, table and test uses only sites at or above it; sites
 * without a probability are left out once it is above 0. It is one value: this
 * field shows and changes the same number on every page.
 */
export default function LocalizationCutoffField({ kind, className }: Props) {
  const { cutoff, available, loaded, belowClassOne, sites, error, update } = usePhosphoLocalizationCutoff();
  const [draft, setDraft] = useState<string>(formatCutoff(cutoff));
  const [invalid, setInvalid] = useState(false);
  const inputId = useId();

  useEffect(() => {
    setDraft(formatCutoff(cutoff));
    setInvalid(false);
  }, [cutoff]);

  if (kind !== undefined && kind !== "phospho") return null;

  const commit = () => {
    const parsed = Number(draft.trim().replace(",", "."));
    if (!Number.isFinite(parsed) || parsed < 0 || parsed > 1) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    const rounded = Math.round(parsed * 100) / 100;
    setDraft(formatCutoff(rounded));
    if (rounded !== cutoff) void update(rounded);
  };

  const disabled = loaded && !available && cutoff === 0;
  return (
    <div className={`block text-sm ${className ?? ""}`}>
      <label htmlFor={inputId} className="mb-2 block font-medium text-slate-700">Localization probability cutoff</label>
      <AssistantInput
        id={inputId}
        type="text"
        lang="en-US"
        inputMode="decimal"
        value={draft}
        disabled={disabled}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
        }}
        aria-invalid={invalid}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
      />
      {invalid || error ? (
        <span className="mt-1 block text-xs text-red-700">
          {invalid ? "Enter a value between 0.00 and 1.00." : error}
        </span>
      ) : null}
      {available && cutoff < 0.75 && belowClassOne > 0 ? (
        <span className="mt-1 block text-xs text-amber-700">
          Non-class I sites included ({belowClassOne.toLocaleString()} of {sites.toLocaleString()} retained sites below 0.75 localization probability).
        </span>
      ) : null}
    </div>
  );
}
