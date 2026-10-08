// Result sections and notices the statistics panels share.

import { withPlotDownloadFilename, withPlotDownloadFormat, type PlotDownloadFormat } from "../../lib/plotDownload";
import PlotDownloadControls from "../../components/PlotDownloadControls";
import { useMemo } from "react";
import { collectColumns, csvDataUrl, rowsToQuotedCsv } from "../../lib/tableData";
import PaginatedTable from "../../components/PaginatedTable";
import PlotImage from "../../components/PlotImage";
import InteractivePlot from "../../components/InteractivePlot";
import NotebookDownload, { type RenderedNotebook } from "../../components/NotebookDownload";
import SelectField from "../../components/SelectField";

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

export function PlotFrame({ title, url, height, notebook, onRendered }: {
  title: string; url: string; height: number; notebook?: RenderedNotebook | null;
  onRendered?: (url: string, token: string | null) => void;
}) {
  const resolvedHeight = Math.max(height, 760);
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <div className="flex flex-wrap items-center gap-2">
          <a href={url} target="_blank" rel="noreferrer" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">
            Open Plot
          </a>
          {onRendered ? <NotebookDownload plotUrl={url} rendered={notebook ?? null} /> : null}
        </div>
      </div>
      {onRendered ? <InteractivePlot url={url} title={title} height={resolvedHeight} onRendered={onRendered} /> :
        <iframe sandbox="allow-scripts allow-downloads" src={url} title={title} className="w-full rounded-xl border border-slate-200 bg-white" style={{ height: resolvedHeight }} />}
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
  notebook,
  onRendered,
}: {
  title: string;
  url: string;
  notebook?: RenderedNotebook | null;
  onRendered?: (url: string, token: string | null) => void;
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
              <PlotDownloadControls label={title} format={download.format} onFormatChange={download.onFormatChange}
                href={withPlotDownloadFormat(url, download.format)} filename={withPlotDownloadFilename(download.filename, download.format)} />
            </>
          ) : null}
          <a href={url} target="_blank" rel="noreferrer" className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">
            Open Image
          </a>
          {onRendered ? <NotebookDownload plotUrl={url} rendered={notebook ?? null} /> : null}
        </div>
      </div>
      <PlotImage url={url} alt={title} onRendered={onRendered} />
    </section>
  );
}

export function TableSection({ title, rows, filename, notebook, plotUrl }: {
  title: string; rows: Record<string, unknown>[]; filename: string;
  notebook?: RenderedNotebook | null; plotUrl?: string;
}) {
  const csvUrl = useMemo(() => {
    if (!rows.length) return null;
    const csv = rowsToQuotedCsv(rows, collectColumns(rows));
    return csvDataUrl(csv);
  }, [rows]);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <div className="flex flex-wrap items-center gap-2">
          {csvUrl ? <a href={csvUrl} download={filename} className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50">Download CSV</a> : null}
          {plotUrl ? <NotebookDownload plotUrl={plotUrl} rendered={notebook ?? null} /> : null}
        </div>
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

type ConditionValue = { value: string; onChange: (value: string) => void };

/**
 * The compared conditions: two selects, or four when each condition is taken
 * relative to its own control. The volcano, ORA and projection panels share it.
 */
export function ConditionPicker({ conditions, condition1, condition2, controls }: {
  conditions: { value: string; label: string }[];
  condition1: ConditionValue;
  condition2: ConditionValue;
  /** Present for control-normalised comparisons. */
  controls?: { condition1: ConditionValue; condition2: ConditionValue };
}) {
  if (controls) {
    return (
      <div className="mt-4 grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
        <SelectField label="Condition 1" value={condition1.value} onChange={condition1.onChange} options={conditions} />
        <SelectField label="Condition 1 Control" value={controls.condition1.value} onChange={controls.condition1.onChange} options={conditions} />
        <SelectField label="Condition 2" value={condition2.value} onChange={condition2.onChange} options={conditions} />
        <SelectField label="Condition 2 Control" value={controls.condition2.value} onChange={controls.condition2.onChange} options={conditions} />
      </div>
    );
  }
  return (
    <div className="mt-4 grid gap-4 lg:grid-cols-2">
      <SelectField label="Condition 1" value={condition1.value} onChange={condition1.onChange} options={conditions} />
      <SelectField label="Condition 2" value={condition2.value} onChange={condition2.onChange} options={conditions} />
    </div>
  );
}
