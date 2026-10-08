/** Notes a plot response carries for the page, shown under the figure (never in it). */

function readNotice(response: Response, header: string): string {
  const raw = response.headers.get(header) ?? "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw; // A malformed notice must not hide the plot.
  }
}

/** Why this figure has no notebook export, when the server could not prepare one. */
function notebookUnavailableNotice(response: Response): string {
  const reason = readNotice(response, "X-CoPYlot-Notebook-Unavailable").trim();
  return reason ? `Notebook export unavailable: ${reason}` : "";
}

/** Every note a plot response carries: the plot's own notice, then any notebook reason. */
export function plotNotices(response: Response): string {
  return [readNotice(response, "X-CoPYlot-Notice").trim(), notebookUnavailableNotice(response)]
    .filter(Boolean).join(" ");
}
