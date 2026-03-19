import type { DatasetPreviewResponse } from "../../lib/types";

type DatasetPreviewProps = {
  dataset: DatasetPreviewResponse;
};

export default function DatasetPreview({ dataset }: DatasetPreviewProps) {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <StatCard label="Dataset ID" value={dataset.datasetId} />
        <StatCard label="Filename" value={dataset.filename} />
        <StatCard label="Kind" value={dataset.kind} />
        <StatCard label="Rows" value={String(dataset.rows)} />
        <StatCard label="Columns" value={String(dataset.columns)} />
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-lg font-semibold">Preview</h2>
          <p className="text-sm text-slate-500">
            First {dataset.preview.length} rows of the uploaded dataset
          </p>
        </div>

        <div className="overflow-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                {dataset.columnNames.map((col) => (
                  <th
                    key={col}
                    className="border-b border-slate-200 px-4 py-3 text-left font-medium text-slate-700"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {dataset.preview.map((row, rowIndex) => (
                <tr key={rowIndex} className="hover:bg-slate-50">
                  {dataset.columnNames.map((col) => (
                    <td
                      key={col}
                      className="border-b border-slate-100 px-4 py-3 align-top text-slate-700"
                    >
                      {String(row[col] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-2 break-all text-base font-semibold text-slate-900">
        {value}
      </div>
    </div>
  );
}