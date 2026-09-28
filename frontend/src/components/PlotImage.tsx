import { useEffect, useState } from "react";
import { plotErrorMessage, PLOT_ERROR_FALLBACK } from "../lib/plotError";

type Props = { url: string; alt: string; className?: string };

export default function PlotImage(props: Props) {
  return <LoadedPlotImage key={props.url} {...props} />;
}

function LoadedPlotImage({ url, alt, className = "w-full rounded-xl border border-slate-200" }: Props) {
  const [result, setResult] = useState<{ image: string; notice: string } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let image = "";
    async function load() {
      try {
        const response = await fetch(url, { signal: controller.signal });
        if (!response.ok) {
          const payload: unknown = await response.json().catch(() => null);
          throw new Error(plotErrorMessage(payload));
        }
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        const header = response.headers.get("X-CoPYlot-Notice") ?? "";
        let notice = header;
        try { notice = decodeURIComponent(header); } catch { /* A malformed notice must not hide the plot. */ }
        image = URL.createObjectURL(blob);
        setResult({ image, notice });
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
    <img src={result.image} alt={alt} className={className} onError={() => setError(PLOT_ERROR_FALLBACK)} />
    {result.notice ? <div role="status" className="mt-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">{result.notice}</div> : null}
  </>;
}
