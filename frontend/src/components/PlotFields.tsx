import NumberField from "./NumberField";
import { AssistantSelect } from "./AssistantFields";
import { clampPlotDimensionCm, clampPlotDpi, MIN_PLOT_DIMENSION_CM, MAX_PLOT_DIMENSION_CM, MIN_PLOT_DPI, MAX_PLOT_DPI } from "../lib/plotLimits";

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
      <NumberField appearance min={MIN_PLOT_DIMENSION_CM} max={MAX_PLOT_DIMENSION_CM} label="Width (cm)" value={widthCm} onChange={(value) => onWidthChange(clampPlotDimensionCm(value))} />
      <NumberField appearance min={MIN_PLOT_DIMENSION_CM} max={MAX_PLOT_DIMENSION_CM} label="Height (cm)" value={heightCm} onChange={(value) => onHeightChange(clampPlotDimensionCm(value))} />
      <NumberField appearance min={MIN_PLOT_DPI} max={MAX_PLOT_DPI} label="DPI" value={dpi} onChange={(value) => onDpiChange(clampPlotDpi(value))} />
    </div>
  );
}
