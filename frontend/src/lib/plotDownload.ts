export type PlotDownloadFormat = "png" | "jpg" | "webp" | "pdf" | "svg";

export const PLOT_DOWNLOAD_FORMAT_OPTIONS: Array<{
  value: PlotDownloadFormat;
  label: string;
}> = [
  { value: "png", label: "PNG" },
  { value: "jpg", label: "JPG" },
  { value: "webp", label: "WEBP" },
  { value: "pdf", label: "PDF" },
  { value: "svg", label: "SVG" },
];

/**
 * The one place a remembered or hand-edited format is checked against what is
 * actually offered. Each page used to inline its own list of formats, so adding
 * one meant finding all six copies before a restored page could use it.
 */
export function coercePlotDownloadFormat(value: unknown): PlotDownloadFormat {
  const text = String(value ?? "").trim().toLowerCase();
  const match = PLOT_DOWNLOAD_FORMAT_OPTIONS.find((option) => option.value === text);
  return match ? match.value : "png";
}

export function withPlotDownloadFormat(url: string, format: PlotDownloadFormat): string {
  if (format === "png") return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}downloadFormat=${encodeURIComponent(format)}`;
}

export function withPlotDownloadFilename(filename: string, format: PlotDownloadFormat): string {
  const stem = filename.replace(/\.(png|jpg|jpeg|webp|pdf|svg)$/i, "");
  return `${stem}.${format}`;
}
