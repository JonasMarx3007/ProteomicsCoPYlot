import { useId, useState } from "react";

// One size control for the whole tool. This file used to carry a second copy
// that rendered DPI, Height, Width -- the same three fields in the opposite
// order from every other page, which is how the same figure ended up described
// two ways depending on where you set it.
export { SizeRow } from "./PlotFields";

export function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export function NumericField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
}) {
  const fieldId = useId();
  const [draft, setDraft] = useState<string | null>(null);
  const displayedValue = draft ?? (Number.isFinite(value) ? String(value) : "");

  const commit = () => {
    const normalized = displayedValue.trim().replace(",", ".");
    if (!normalized) {
      setDraft(null);
      return;
    }
    const parsed = Number(normalized);
    if (!Number.isFinite(parsed)) {
      setDraft(null);
      return;
    }
    onChange(parsed);
    setDraft(null);
  };

  return (
    <div>
      <label htmlFor={fieldId} className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <input id={fieldId}
        type="text"
        lang="en-US"
        inputMode="decimal"
        value={displayedValue}
        onChange={(e) => {
          const normalized = e.target.value.replace(",", ".");
          setDraft(normalized);
          const parsed = Number(normalized);
          if (Number.isFinite(parsed)) {
            onChange(parsed);
          }
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit();
          }
        }}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
      />
    </div>
  );
}
