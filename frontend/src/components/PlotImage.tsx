import { useEffect, useState } from "react";
import { plotErrorMessage, PLOT_ERROR_FALLBACK } from "../lib/plotError";
import { fetchPlot } from "../lib/fetchPlot";
import { notebookUnavailableNotice, readNotice } from "../lib/plotNotice";

type Props = { url: string; alt: string; className?: string;
  onRendered?: (url: string, notebookToken: string | null) => void };

export default function PlotImage(props: Props) {
  return <LoadedPlotImage key={props.url} {...props} />;
}

function LoadedPlotImage({ url, alt, onRendered, className = "w-full rounded-xl border border-slate-200" }: Props) {
  const [result, setResult] = useState<{ image: string; notice: string; notebookToken: string | null } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let image = "";
    async function load() {
      try {
        const response = await fetchPlot(url, controller.signal);
        if (!response.ok) {
          const payload: unknown = await response.json().catch(() => null);
          throw new Error(plotErrorMessage(payload));
        }
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        const notice = [readNotice(response, "X-CoPYlot-Notice"), notebookUnavailableNotice(response)]
          .filter(Boolean).join(" ");
        image = URL.createObjectURL(blob);
        const candidate = response.headers.get("X-CoPYlot-Notebook") ?? "";
        const notebookToken = /^[A-Za-z0-9_-]{32}$/.test(candidate) ? candidate : null;
        setResult({ image, notice, notebookToken });
      } catch (cause) {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : PLOT_ERROR_FALLBACK);
        }
      }
    }
    void load();
    return () => {
      controller.abort();
      if (image) URL.revokeObjectURL(image);
    };
  }, [url]);

  if (error) return <div role="status" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>;
  if (!result) return <div role="status" className="text-sm text-slate-600">Loading plot…</div>;
  return <>
    <img src={result.image} alt={alt} className={className}
      onLoad={() => onRendered?.(url, result.notebookToken)}
      onError={() => { setError(PLOT_ERROR_FALLBACK); onRendered?.(url, null); }} />
    {result.notice ? <div role="status" className="mt-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{result.notice}</div> : null}
  </>;
}
