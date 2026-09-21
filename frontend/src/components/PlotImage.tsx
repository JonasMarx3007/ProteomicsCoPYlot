import { useState } from "react";
import HeatmapImage from "./HeatmapImage";
import { plotErrorMessage, PLOT_ERROR_FALLBACK } from "../lib/plotError";

/**
 * A rendered plot, or the reason there is none — never both.
 *
 * Every plot page carried its own copy of this, and every copy had the same
 * flaw: the `<img>` stayed on the page after the request failed, so the
 * browser's broken-image icon sat above the explanation. A refusal like "no
 * matching pathway genes were found in the current dataset" is an answer, not a
 * failure to render, and it reads as one only when it replaces the figure
 * instead of accompanying a broken one.
 *
 * An `<img>` cannot see the body of a 400, so the failure handler asks for the
 * same URL again and reads `detail` out of it. The state is keyed by URL, which
 * is what makes the next attempt happen: change any control and the URL changes
 * with it, so the image is tried again rather than staying suppressed.
 */
export default function PlotImage({
  url,
  alt,
  className = "w-full rounded-xl border border-slate-200",
}: {
  url: string;
  alt: string;
  className?: string;
}) {
  const [failure, setFailure] = useState<{ url: string; message: string } | null>(null);

  async function explainFailure(target: string) {
    try {
      const response = await fetch(target);
      if (!response.ok) {
        const payload: unknown = await response.json().catch(() => null);
        setFailure({ url: target, message: plotErrorMessage(payload) });
        return;
      }
    } catch {
      // The second request failed too; the generic message is all there is.
    }
    setFailure({
      url: target,
      message: PLOT_ERROR_FALLBACK,
    });
  }

  if (failure?.url === url) {
    return (
      <div
        role="status"
        className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        {failure.message}
      </div>
    );
  }

  if (/\/(?:anova|pathway-heatmap|heatmap)\.png(?:\?|$)/.test(url)) {
    return <HeatmapImage key={url} url={url} alt={alt} className={className} />;
  }

  return (
    <img
      key={url}
      src={url}
      alt={alt}
      className={className}
      onError={() => void explainFailure(url)}
    />
  );
}
