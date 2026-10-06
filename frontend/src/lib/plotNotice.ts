/** Notes a plot response carries for the page, shown under the figure (never in it). */

export function readNotice(response: Response, header: string): string {
  const raw = response.headers.get(header) ?? "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw; // A malformed notice must not hide the plot.
  }
}

/** Why this figure has no notebook export, when the server could not prepare one. */
export function notebookUnavailableNotice(response: Response): string {
  const reason = readNotice(response, "X-CoPYlot-Notebook-Unavailable").trim();
  return reason ? `Notebook export unavailable: ${reason}` : "";
}
