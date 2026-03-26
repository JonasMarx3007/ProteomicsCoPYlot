export type PlotDownloadFormat = "png" | "jpg" | "webp" | "pdf";

export const PLOT_DOWNLOAD_FORMAT_OPTIONS: Array<{
  value: PlotDownloadFormat;
  label: string;
}> = [
  { value: "png", label: "PNG" },
  { value: "jpg", label: "JPG" },
  { value: "webp", label: "WEBP" },
  { value: "pdf", label: "PDF" },
];

export function withPlotDownloadFormat(url: string, format: PlotDownloadFormat): string {
  if (format === "png") return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}downloadFormat=${encodeURIComponent(format)}`;
}

export function withPlotDownloadFilename(filename: string, format: PlotDownloadFormat): string {
  const stem = filename.replace(/\.(png|jpg|jpeg|webp|pdf)$/i, "");
  return `${stem}.${format}`;
}
