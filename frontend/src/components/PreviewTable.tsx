import { useMemo } from "react";
import { displayLabel, visibleColumns } from "../lib/columnLabels";
import { collectColumns } from "../lib/tableData";

/**
 * A scrollable preview of table rows.
 *
 * Four pages carried the same copy of this and two more carried near-copies.
 * The shape kept here is theirs: fixed layout with each cell truncated to about
 * 28 characters and its full text in the tooltip, so one long protein-group
 * string cannot stretch a column past the panel.
 */
export default function PreviewTable({
  rows,
  emptyText,
  downloadAction,
  labels,
  plotSummary = false,
}: {
  rows: Record<string, unknown>[];
  emptyText: string;
  /** A button above the table, for pages that offer the full file. */
  downloadAction?: { label: string; onClick: () => void | Promise<void>; disabled?: boolean };
  /** Header text for columns whose shared label does not fit this table. */
  labels?: Record<string, string>;
  /** Only plot summary schemas reserve x/y/color_val for drawing coordinates. */
  plotSummary?: boolean;
}) {
  // Data keys stay as they are (the CSV downloads use them); the header shows the label.
  const columns = useMemo(() => visibleColumns(collectColumns(rows ?? []), plotSummary), [rows, plotSummary]);

  if (!rows || rows.length === 0 || columns.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        {emptyText}
      </div>
    );
  }

  const table = (
    <div className="max-h-[28rem] overflow-auto rounded-xl border border-slate-200">
      <table className="min-w-full table-fixed border-collapse text-sm">
        <thead className="bg-slate-50">
          <tr>
            {columns.map((column) => (
              <th
                key={column}
                className="border-b border-slate-200 px-3 py-2 text-left font-medium text-slate-700"
                title={column}
              >
                {displayLabel(column, labels)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex} className="odd:bg-white even:bg-slate-50/50">
              {columns.map((column) => {
                const value = row[column];
                const text = value == null ? "" : String(value);
                return (
                  <td
                    key={`${rowIndex}-${column}`}
                    className="border-b border-slate-100 px-3 py-2 text-slate-600"
                    title={text}
                  >
                    <div className="max-w-[28ch] overflow-hidden text-ellipsis whitespace-nowrap">
                      {text}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );

  if (!downloadAction) return table;
  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={downloadAction.onClick}
        disabled={Boolean(downloadAction.disabled)}
        className="inline-flex rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
      >
        {downloadAction.label}
      </button>
      {table}
    </div>
  );
}
