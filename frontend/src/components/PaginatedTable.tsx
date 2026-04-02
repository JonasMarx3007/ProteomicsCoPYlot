import { useEffect, useMemo, useState } from "react";

type Props = {
  rows: Record<string, unknown>[];
  emptyText?: string;
  pageSize?: number;
  maxHeightClassName?: string;
};

export default function PaginatedTable({
  rows,
  emptyText = "No rows available.",
  pageSize = 50,
  maxHeightClassName = "max-h-[28rem]",
}: Props) {
  const resolvedPageSize = Math.max(1, Math.round(pageSize));
  const [page, setPage] = useState(1);

  const columns = useMemo(() => {
    const keys = new Set<string>();
    rows.forEach((row) => {
      Object.keys(row).forEach((key) => keys.add(key));
    });
    return Array.from(keys);
  }, [rows]);

  const totalPages = Math.max(1, Math.ceil(rows.length / resolvedPageSize));

  useEffect(() => {
    setPage(1);
  }, [rows, resolvedPageSize]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  if (!rows || rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        {emptyText}
      </div>
    );
  }

  const start = (page - 1) * resolvedPageSize;
  const end = Math.min(rows.length, start + resolvedPageSize);
  const visibleRows = rows.slice(start, end);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
        <div>
          Showing rows {start + 1}-{end} of {rows.length}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPage((current) => Math.max(1, current - 1))}
            disabled={page <= 1}
            className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50"
          >
            Prev
          </button>
          <span className="min-w-20 text-center text-xs">
            Page {page} / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
            disabled={page >= totalPages}
            className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>
      <div className={`${maxHeightClassName} overflow-auto rounded-xl border border-slate-200`}>
        <table className="min-w-full divide-y divide-slate-200">
          <thead className="bg-slate-50">
            <tr>
              {columns.map((column) => (
                <th
                  key={column}
                  className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-600"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {visibleRows.map((row, index) => (
              <tr key={start + index} className={(start + index) % 2 ? "bg-slate-50/40" : "bg-white"}>
                {columns.map((column) => (
                  <td key={column} className="px-4 py-2 align-top text-sm text-slate-700">
                    {formatCellValue(row[column])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatCellValue(value: unknown) {
  if (value == null) return "";
  if (typeof value === "number") {
    if (Number.isInteger(value)) return String(value);
    return value.toFixed(4);
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

