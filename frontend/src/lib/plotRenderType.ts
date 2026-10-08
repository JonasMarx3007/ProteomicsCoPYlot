/**
 * The rule for every plot offered as a static/interactive pair.
 *
 * Static is the figure you take away: it has a width, a height and a DPI, and
 * it is exported through the format selector (PNG, JPG, WEBP, SVG, PDF).
 *
 * Interactive is for exploring: it fills its frame, Plotly's own camera button
 * saves a picture of it, and "Open (Interactive) Plot" opens it in a new
 * window. It has no size and no export control, and it is not sent the static
 * figure's size either -- otherwise a width typed for the print figure would
 * quietly change the interactive one, through a control that is not on screen.
 *
 * `frontend/tests/unit/plot-render-type-rule.test.tsx` holds every pair to this.
 */

const STATIC_SIZE_KEYS = ["widthCm", "heightCm", "dpi"] as const;

type StaticSizeKey = (typeof STATIC_SIZE_KEYS)[number];

export function withoutStaticSize<T extends object>(params: T): Omit<T, StaticSizeKey> {
  const copy: Record<string, unknown> = { ...(params as Record<string, unknown>) };
  for (const key of STATIC_SIZE_KEYS) delete copy[key];
  return copy as Omit<T, StaticSizeKey>;
}
