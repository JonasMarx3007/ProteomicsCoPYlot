/**
 * plotly.js for interactive plots, fetched once per version and reused.
 *
 * The server sends the app's interactive plots without their 4.8 MB inline
 * plotly.js when asked (SHARED_PLOTLY_HEADER); the page names the versioned
 * asset in X-CoPYlot-Plotly-Asset. The source is put back inline before the
 * page is shown, so the sandboxed frame and its inline-only CSP are unchanged.
 * Downloads never ask, and stay self-contained.
 */
import { TAB_API_BASE } from "./tabSession";

export const SHARED_PLOTLY_HEADER = "X-CoPYlot-Shared-Plotly";
export const PLOTLY_MARKER = "/*copylot-shared-plotly*/";
const ASSET = /^\/api\/runtime\/plotly-[0-9A-Za-z.+-]+\.js$/;
const sources = new Map<string, Promise<string>>();

function loadAsset(path: string): Promise<string> {
  let source = sources.get(path);
  if (!source) {
    source = fetch(path).then(async (response) => {
      if (!response.ok) throw new Error("Could not load the plotting library.");
      return response.text();
    });
    source.catch(() => sources.delete(path));
    sources.set(path, source);
  }
  return source;
}

/** The plot page as the frame shows it: plotly.js inline again. */
export async function withSharedPlotly(html: string, response: Response): Promise<string> {
  const asset = response.headers.get("X-CoPYlot-Plotly-Asset") ?? "";
  if (!html.includes(PLOTLY_MARKER) || !ASSET.test(asset)) return html;
  const source = await loadAsset(`${TAB_API_BASE}${asset}`);
  // A function replacement: plotly.js contains "$" sequences a string would expand.
  return html.replace(PLOTLY_MARKER, () => source);
}
