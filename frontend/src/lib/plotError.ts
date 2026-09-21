export const PLOT_ERROR_FALLBACK = "Failed to load the plot image. Check the selected data and plot options.";

export function plotErrorMessage(payload: unknown): string {
  if (!payload || typeof payload !== "object" || !("detail" in payload)) return PLOT_ERROR_FALLBACK;
  const details = Array.isArray(payload.detail) ? payload.detail : [payload.detail];
  const messages = details.map(detail => {
    const message = typeof detail === "string" ? detail
      : detail && typeof detail === "object" && "msg" in detail ? detail.msg : null;
    return typeof message === "string" ? message.trim() : "";
  }).filter(Boolean);
  return [...new Set(messages)].slice(0, 3).join("; ") || PLOT_ERROR_FALLBACK;
}
