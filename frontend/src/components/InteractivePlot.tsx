import { useEffect, useRef, useState } from "react";
import { plotErrorMessage, PLOT_ERROR_FALLBACK } from "../lib/plotError";
import { fetchPlot } from "../lib/fetchPlot";
import { plotNotices } from "../lib/plotNotice";
import { SHARED_PLOTLY_HEADER, withSharedPlotly } from "../lib/sharedPlotly";

type Props = { url: string; title: string; height: number | string;
  onRendered: (url: string, token: string | null) => void };

export default function InteractivePlot(props: Props) {
  return <LoadedInteractivePlot key={props.url} {...props} />;
}

function LoadedInteractivePlot({ url, title, height, onRendered }: Props) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [result, setResult] = useState<{ html: string; token: string | null; nonce: string; notice: string } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetchPlot(url, controller.signal, { [SHARED_PLOTLY_HEADER]: "1" });
        if (!response.ok) throw new Error(plotErrorMessage(await response.json().catch(() => null)));
        const html = await withSharedPlotly(await response.text(), response);
        if (controller.signal.aborted) return;
        const candidate = response.headers.get("X-CoPYlot-Notebook") ?? "";
        const token = /^[A-Za-z0-9_-]{32}$/.test(candidate) ? candidate : null;
        const nonce = Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, "0")).join("");
        // The server emits this event after Plotly's render promise resolves.
        // Keep the frame sandboxed: readiness is the only message accepted.
        const ready = `<script>window.addEventListener('copylot-plot-ready',function(){parent.postMessage({type:'copylot-plot-ready',nonce:${JSON.stringify(nonce)}},'*')},{once:true});</script>`;
        setResult({ html: html.replace("</head>", ready + "</head>"), token, nonce, notice: plotNotices(response) });
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : PLOT_ERROR_FALLBACK);
      }
    }
    void load();
    return () => controller.abort();
  }, [url]);

  useEffect(() => {
    const ready = (event: MessageEvent) => {
      if (result && event.source === frame.current?.contentWindow
        && event.data?.type === "copylot-plot-ready" && event.data?.nonce === result.nonce) {
        onRendered(url, result.token);
      }
    };
    window.addEventListener("message", ready);
    return () => window.removeEventListener("message", ready);
  }, [result, url, onRendered]);

  if (error) return <div role="alert" className="text-sm text-red-700">{error}</div>;
  if (!result) return <div role="status" className="text-sm text-slate-600">Loading plot…</div>;
  return <>
    <iframe ref={frame} sandbox="allow-scripts allow-downloads" srcDoc={result.html} title={title}
      className="w-full rounded-xl border border-slate-200" style={{ height }} />
    {result.notice ? <div role="status" className="mt-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{result.notice}</div> : null}
  </>;
}
