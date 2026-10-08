import { AssistantSelect } from "./AssistantFields";
import { PLOT_DOWNLOAD_FORMAT_OPTIONS, type PlotDownloadFormat } from "../lib/plotDownload";

/** The format choice and the "Download Plot" link every plot offers. */
export default function PlotDownloadControls({ label, format, onFormatChange, href, filename }: {
  /** Names the format control: "<label> download format". */
  label: string;
  format: PlotDownloadFormat;
  onFormatChange: (format: PlotDownloadFormat) => void;
  href: string;
  filename: string;
}) {
  return (
    <>
      <AssistantSelect
        aria-label={`${label} download format`}
        value={format}
        onChange={(event) => onFormatChange(event.target.value as PlotDownloadFormat)}
        className="rounded-xl border border-slate-300 bg-white px-2 py-2 text-sm text-slate-700 outline-none focus:border-slate-900"
      >
        {PLOT_DOWNLOAD_FORMAT_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </AssistantSelect>
      <a href={href} download={filename}
        className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">
        Download Plot
      </a>
    </>
  );
}
