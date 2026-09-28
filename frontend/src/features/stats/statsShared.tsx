// Result sections and notices the statistics panels share.

import { PLOT_DOWNLOAD_FORMAT_OPTIONS, withPlotDownloadFilename, withPlotDownloadFormat, type PlotDownloadFormat } from "../../lib/plotDownload";
import { AssistantSelect } from "../../components/AssistantFields";
import { useMemo } from "react";
import { collectColumns, rowsToQuotedCsv } from "../../lib/tableData";
import PaginatedTable from "../../components/PaginatedTable";
import PlotImage from "../../components/PlotImage";

export function Notice({ error, warnings }: { error: string | null; warnings?: string[] }) {
  if (!error && (!warnings || warnings.length === 0)) return null;
  return (
    <div className="mt-4 space-y-3">
      {error ? <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div> : null}
      {warnings && warnings.length > 0 ? <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{warnings.join(" ")}</div> : null}
    </div>
  );
}

export function SummarySection({ items, warnings }: { items: { label: string; value: string }[]; warnings?: string[] }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {items.map((item) => (
          <div key={item.label} className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{item.label}</div>
            <div className="mt-1 text-sm font-semibold text-slate-900">{item.value}</div>
          </div>
        ))}
      </div>
      {warnings && warnings.length > 0 ? <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{warnings.join(" ")}</div> : null}
    </section>
  );
}

export function PlotFrame({ title, url, height }: { title: string; url: string; height: number }) {
  const resolvedHeight = Math.max(height, 760);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <a href={url} target="_blank" rel="noreferrer" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">
          Open Plot
        </a>
      </div>
      <iframe sandbox="allow-scripts allow-downloads" src={url} title={title} className="w-full rounded-xl border border-slate-200 bg-white" style={{ height: resolvedHeight }} />
    </section>
  );
}

// A plot on this page, optionally with its own export control. `download` is
// what turns the section from a picture into a deliverable: the format is the
// caller's state so that it can be remembered with the rest of the panel, and
// the file name is the caller's too, because only the panel knows which
// conditions and which dataset level produced the figure.
export function ImageSection({
  title,
  url,
  download,
}: {
  title: string;
  url: string;
  download?: {
    filename: string;
    format: PlotDownloadFormat;
    onFormatChange: (format: PlotDownloadFormat) => void;
  };
}) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <div className="flex flex-wrap items-center gap-2">
          {download ? (
            <>
              <AssistantSelect
                aria-label={`${title} download format`}
                value={download.format}
                onChange={(e) => download.onFormatChange(e.target.value as PlotDownloadFormat)}
                className="rounded-xl border border-slate-300 bg-white px-2 py-2 text-sm text-slate-700 outline-none focus:border-slate-900"
              >
                {PLOT_DOWNLOAD_FORMAT_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </AssistantSelect>
              <a
                href={withPlotDownloadFormat(url, download.format)}
                download={withPlotDownloadFilename(download.filename, download.format)}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download Plot
              </a>
            </>
          ) : null}
          <a href={url} target="_blank" rel="noreferrer" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">
            Open Image
          </a>
        </div>
      </div>
      <PlotImage url={url} alt={title} />
    </section>
  );
}

export function TableSection({ title, rows, filename }: { title: string; rows: Record<string, unknown>[]; filename: string }) {
  const csvUrl = useMemo(() => {
    if (!rows.length) return null;
    const csv = rowsToQuotedCsv(rows, collectColumns(rows));
    return `data:text/csv;charset=utf-8,${encodeURIComponent(csv)}`;
  }, [rows]);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        {csvUrl ? <a href={csvUrl} download={filename} className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">Download CSV</a> : null}
      </div>
      <StatsResultTable rows={rows} />
    </section>
  );
}

function StatsResultTable({ rows }: { rows: Record<string, unknown>[] }) {
  return <PaginatedTable rows={rows} pageSize={50} emptyText="No rows available." maxHeightClassName="max-h-[36rem]" />;
}

export function InfoSection({ message }: { message: string }) {
  return (
    <section className="rounded-2xl border border-sky-200 bg-sky-50 p-6 shadow-sm">
      <div className="text-sm text-sky-800">{message}</div>
    </section>
  );
}
