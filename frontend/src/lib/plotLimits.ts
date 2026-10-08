// The backend's own limits (backend/app/services/plot_limits.py), exported by
// `npm run generate:api`, so the controls cannot offer a size the request is
// then refused for. Width and height share one pair of limits.
import limits from "./generated/plotLimits.json";

export const MIN_PLOT_DIMENSION_CM = Math.max(limits.MIN_PLOT_WIDTH_CM, limits.MIN_PLOT_HEIGHT_CM);
export const MAX_PLOT_DIMENSION_CM = Math.min(limits.MAX_PLOT_WIDTH_CM, limits.MAX_PLOT_HEIGHT_CM);
export const MIN_PLOT_DPI = limits.MIN_PLOT_DPI;
export const MAX_PLOT_DPI = limits.MAX_PLOT_DPI;
const MAX_PLOT_PIXELS = limits.MAX_PLOT_PIXELS;
const HTML_LAYOUT_DPI = limits.HTML_LAYOUT_DPI;

export function clampPlotDimensionCm(value: number): number {
  if (!Number.isFinite(value)) return MIN_PLOT_DIMENSION_CM;
  return Math.min(MAX_PLOT_DIMENSION_CM, Math.max(MIN_PLOT_DIMENSION_CM, value));
}

export function clampPlotDpi(value: number): number {
  if (!Number.isFinite(value)) return MIN_PLOT_DPI;
  return Math.min(MAX_PLOT_DPI, Math.max(MIN_PLOT_DPI, Math.round(value)));
}

/** Nothing usable was saved: absent, empty, or not a finite number. `Number("")`
 * is 0, so an empty string has to be caught before it is converted. */
function isMissing(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === "string" && !value.trim()) return true;
  return !Number.isFinite(savedNumber(value));
}

function savedNumber(value: unknown): number {
  return typeof value === "string" ? Number(value.replace(",", ".")) : Number(value);
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
  if (isMissing(value)) {
    return clampPlotDimensionCm(fallback);
  }
  return clampPlotDimensionCm(savedNumber(value));
}

/** A saved DPI, or the plot's default when nothing usable was saved. */
export function restorePlotDpi(value: unknown, fallback: number): number {
  if (isMissing(value)) {
    return clampPlotDpi(fallback);
  }
  return clampPlotDpi(savedNumber(value));
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

/** Frame height in px for an interactive plot drawn `heightCm` tall, with room for its controls. */
export function iframeHeightForPlot(
  heightCm: number, { fallbackCm, minPx, paddingPx }: { fallbackCm: number; minPx: number; paddingPx: number },
): number {
  const basePx = ((Number.isFinite(heightCm) ? heightCm : fallbackCm) * 96) / 2.54;
  return Math.max(minPx, Math.round(basePx + paddingPx));
}
