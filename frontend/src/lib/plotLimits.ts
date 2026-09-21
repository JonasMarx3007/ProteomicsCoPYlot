export const MIN_PLOT_DIMENSION_CM = 1;
export const MAX_PLOT_DIMENSION_CM = 60;
export const MIN_PLOT_DPI = 72;
export const MAX_PLOT_DPI = 600;
export const MAX_PLOT_PIXELS = 24_000_000;
export const HTML_LAYOUT_DPI = 96;

export function clampPlotDimensionCm(value: number): number {
  if (!Number.isFinite(value)) return MIN_PLOT_DIMENSION_CM;
  return Math.min(MAX_PLOT_DIMENSION_CM, Math.max(MIN_PLOT_DIMENSION_CM, value));
}

export function clampPlotDpi(value: number): number {
  if (!Number.isFinite(value)) return MIN_PLOT_DPI;
  return Math.min(MAX_PLOT_DPI, Math.max(MIN_PLOT_DPI, Math.round(value)));
}

/**
 * A saved width or height, or the plot's default when nothing usable was saved.
 *
 * Save files outlive the code that wrote them: a key can be missing, or hold a
 * string, or `null`. `Number(null)` is `0`, which would ask the backend for a
 * figure 0 cm wide, so anything that is not a finite number falls back to the
 * default the page ships with rather than to a value no one chose.
 */
export function restorePlotDimensionCm(value: unknown, fallback: number): number {
  const parsed = typeof value === "string" ? Number(value.replace(",", ".")) : Number(value);
  if (value === null || value === undefined || !Number.isFinite(parsed)) {
    return clampPlotDimensionCm(fallback);
  }
  return clampPlotDimensionCm(parsed);
}

/** A saved DPI, or the plot's default when nothing usable was saved. */
export function restorePlotDpi(value: unknown, fallback: number): number {
  const parsed = typeof value === "string" ? Number(value.replace(",", ".")) : Number(value);
  if (value === null || value === undefined || !Number.isFinite(parsed)) {
    return clampPlotDpi(fallback);
  }
  return clampPlotDpi(parsed);
}

export function normalizePlotSizeParams(
  params: Record<string, string | number | boolean>
): Record<string, string | number | boolean> {
  const normalized = { ...params };
  const hasWidth = "widthCm" in normalized;
  const hasHeight = "heightCm" in normalized;
  const hasDpi = "dpi" in normalized;

  if (hasWidth) normalized.widthCm = clampPlotDimensionCm(Number(normalized.widthCm));
  if (hasHeight) normalized.heightCm = clampPlotDimensionCm(Number(normalized.heightCm));
  if (hasDpi) normalized.dpi = clampPlotDpi(Number(normalized.dpi));

  if (hasWidth && hasHeight) {
    const widthCm = Number(normalized.widthCm);
    const heightCm = Number(normalized.heightCm);
    const requestedDpi = hasDpi ? Number(normalized.dpi) : HTML_LAYOUT_DPI;
    const maxAreaDpi = Math.floor(
      Math.sqrt((MAX_PLOT_PIXELS * 2.54 * 2.54) / (widthCm * heightCm))
    );
    if (hasDpi) {
      normalized.dpi = clampPlotDpi(Math.min(requestedDpi, maxAreaDpi));
    }
  }
  return normalized;
}
