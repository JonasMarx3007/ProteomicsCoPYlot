import { useEffect, useState } from "react";
import { plotErrorMessage } from "../lib/plotError";

export default function HeatmapImage({ url, alt, className }: {
  url: string;
  alt: string;
  className: string;
}) {
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
        const notice = decodeURIComponent(response.headers.get("X-CoPYlot-Notice") ?? "");
        image = URL.createObjectURL(blob);
        setResult({ image, notice });
      } catch (cause) {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "Failed to load the heatmap.");
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
  if (!result) return <div role="status" className="text-sm text-slate-600">Loading heatmap…</div>;
  return <>
    <img src={result.image} alt={alt} className={className} onError={() => setError("Failed to display the heatmap image.")} />
    {result.notice ? <div role="status" className="mt-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">{result.notice}</div> : null}
  </>;
}
