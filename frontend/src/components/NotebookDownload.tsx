import { useState } from "react";
import { buildPlotUrl } from "../lib/api";
import { IS_VIEWER_MODE } from "../lib/appMode";
import { fetchPlot } from "../lib/fetchPlot";
import { plotErrorMessage } from "../lib/plotError";

export type RenderedNotebook = { url: string; token: string | null };

const TOKEN = /^[A-Za-z0-9_-]{32}$/;

/** Only a plot or table URL can be asked again for a fresh export of the same output. */
function renewable(plotUrl: string, outputLabel: string): boolean {
  return outputLabel !== "report" && /^(?:https?:\/\/[^/]+)?\/api\//.test(plotUrl);
}

/**
 * Render the same output again on the server to get a new export of it.
 *
 * Exports are kept for a while per session; an old one can have expired or
 * been replaced by newer ones. The URL is the one already on screen, so the
 * server draws the identical figure or table and hands out a new token for it.
 */
async function renewToken(plotUrl: string): Promise<string | null> {
  const controller = new AbortController();
  const response = await fetchPlot(plotUrl, controller.signal);
  if (!response.ok) return null;
  const header = response.headers.get("X-CoPYlot-Notebook") ?? "";
  if (TOKEN.test(header)) return header;
  if ((response.headers.get("content-type") ?? "").includes("application/json")) {
    const body: unknown = await response.json().catch(() => null);
    const token = (body as { notebookToken?: unknown } | null)?.notebookToken;
    return typeof token === "string" && TOKEN.test(token) ? token : null;
  }
  return null;
}

export default function NotebookDownload({ plotUrl, rendered, outputLabel = 'plot' }: {
  plotUrl: string; rendered: RenderedNotebook | null; outputLabel?: 'plot' | 'table' | 'report';
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [renewed, setRenewed] = useState<RenderedNotebook | null>(null);
  // Viewers may download plots and tables, not notebook exports (D11).
  if (IS_VIEWER_MODE) return null;
  const token = renewed?.url === plotUrl && renewed.token ? renewed.token
    : rendered?.url === plotUrl ? rendered.token : null;

  async function download() {
    if (!token || busy) return;
    setBusy(true);
    setError("");
    let objectUrl = "";
    try {
      const zip = (value: string) => fetch(buildPlotUrl(`/api/plots/notebooks/${encodeURIComponent(value)}.zip`));
      let response = await zip(token);
      if (response.status === 404) {
        if (!renewable(plotUrl, outputLabel)) {
          throw new Error(outputLabel === "report"
            ? "This report's notebook has expired. Generate the report again to export it."
            : `This ${outputLabel}'s notebook has expired. Run it again to export it.`);
        }
        const fresh = await renewToken(plotUrl);
        if (!fresh) throw new Error(`This ${outputLabel} could not be prepared again for export. Change a setting and back to redraw it.`);
        setRenewed({ url: plotUrl, token: fresh });
        response = await zip(fresh);
      }
      if (!response.ok) throw new Error(plotErrorMessage(await response.json().catch(() => null)));
      const filename = /filename="([A-Za-z0-9_.-]+\.zip)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1]
        ?? "CoPYlot_plot_notebook.zip";
      objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      // Let the browser consume the download before releasing its temporary URL.
      const downloadedUrl = objectUrl;
      window.setTimeout(() => URL.revokeObjectURL(downloadedUrl), 30_000);
      objectUrl = "";
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Notebook download failed.");
    } finally {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setBusy(false);
    }
  }

  return <>
    <button type="button" onClick={() => void download()} disabled={!token || busy}
      title={token ? `Export this ${outputLabel} as a reproducible Python notebook` : `Waiting for an exportable ${outputLabel}`}
      className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:opacity-50">
      {busy ? "Preparing notebook…" : "Export notebook"}
    </button>
    {error ? <span role="alert" className="text-sm text-red-700">{error}</span> : null}
  </>;
}
