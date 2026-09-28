import { AssistantInput, AssistantSelect } from "./AssistantFields";
import { useState } from "react";
import { clampPlotDimensionCm, clampPlotDpi, MIN_PLOT_DIMENSION_CM, MAX_PLOT_DIMENSION_CM, MIN_PLOT_DPI, MAX_PLOT_DPI } from "../lib/plotLimits";

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
    <label className="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
      <AssistantInput
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-500"
      />
      {label}
    </label>
  );
}

export function MultiSelectField({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string[];
  options: string[];
  onChange: (value: string[]) => void;
}) {
  const visibleRows = Math.max(4, Math.min(8, options.length || 4));
  return (
    <label className="block text-sm">
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <AssistantSelect
        multiple
        size={visibleRows}
        value={value}
        onChange={(event) => {
          const selected = Array.from(event.currentTarget.selectedOptions).map((option) => option.value);
          onChange(selected);
        }}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </AssistantSelect>
      <span className="mt-1 block text-xs text-slate-500">Use Ctrl/Cmd-click for multi-select.</span>
    </label>
  );
}

export function NumericField({
  label,
  value,
  onChange,
  appearance = false,
  min,
  max,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  appearance?: boolean;
  min?: number;
  max?: number;
}) {
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
    <label className="block text-sm" data-assistant-appearance={appearance ? "true" : undefined}>
      <span className="mb-2 block font-medium text-slate-700">{label}</span>
      <AssistantInput
        type="text"
        data-assistant-permission={appearance ? "view" : undefined}
        min={min}
        max={max}
        lang="en-US"
        inputMode="decimal"
        value={displayedValue}
        onChange={(event) => {
          const normalized = event.target.value.replace(",", ".");
          setDraft(normalized);
          const parsed = Number(normalized);
          if (Number.isFinite(parsed)) {
            onChange(parsed);
          }
        }}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
        }}
        className="w-full rounded-xl border border-slate-300 px-3 py-2 outline-none focus:border-slate-900"
      />
    </label>
  );
}

export function SizeRow({
  widthCm,
  heightCm,
  dpi,
  onWidthChange,
  onHeightChange,
  onDpiChange,
}: {
  widthCm: number;
  heightCm: number;
  dpi: number;
  onWidthChange: (value: number) => void;
  onHeightChange: (value: number) => void;
  onDpiChange: (value: number) => void;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <NumericField appearance min={MIN_PLOT_DIMENSION_CM} max={MAX_PLOT_DIMENSION_CM} label="Width (cm)" value={widthCm} onChange={(value) => onWidthChange(clampPlotDimensionCm(value))} />
      <NumericField appearance min={MIN_PLOT_DIMENSION_CM} max={MAX_PLOT_DIMENSION_CM} label="Height (cm)" value={heightCm} onChange={(value) => onHeightChange(clampPlotDimensionCm(value))} />
      <NumericField appearance min={MIN_PLOT_DPI} max={MAX_PLOT_DPI} label="DPI" value={dpi} onChange={(value) => onDpiChange(clampPlotDpi(value))} />
    </div>
  );
}
