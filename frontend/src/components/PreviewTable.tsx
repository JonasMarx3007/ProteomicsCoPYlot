import { collectColumns, formatCellValue } from "../lib/tableData";

export default function PreviewTable({
  rows,
  emptyText,
}: {
  rows: Record<string, unknown>[];
  emptyText: string;
}) {
  if (!rows || rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
        {emptyText}
      </div>
    );
  }

  const columns = collectColumns(rows);
  return (
    <div className="max-h-[28rem] overflow-auto rounded-xl border border-slate-200">
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
          {rows.map((row, index) => (
            <tr key={index} className={index % 2 ? "bg-slate-50/40" : "bg-white"}>
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
  );
}
