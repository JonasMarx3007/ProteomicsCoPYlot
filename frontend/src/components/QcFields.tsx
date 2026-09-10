import { useId, useState } from "react";
import { clampPlotDimensionCm, clampPlotDpi } from "../lib/plotLimits";

export function SizeRow({
  dpi,
  heightCm,
  widthCm,
  onDpiChange,
  onHeightChange,
  onWidthChange,
}: {
  dpi: number;
  heightCm: number;
  widthCm: number;
  onDpiChange: (value: number) => void;
  onHeightChange: (value: number) => void;
  onWidthChange: (value: number) => void;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <NumericField label="DPI" value={dpi} onChange={(value) => onDpiChange(clampPlotDpi(value))} />
      <NumericField label="Height (cm)" value={heightCm} onChange={(value) => onHeightChange(clampPlotDimensionCm(value))} />
      <NumericField label="Width (cm)" value={widthCm} onChange={(value) => onWidthChange(clampPlotDimensionCm(value))} />
    </div>
  );
}

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
