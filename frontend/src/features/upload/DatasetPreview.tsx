import type { DatasetPreviewResponse } from "../../lib/types";

type DatasetPreviewProps = {
  dataset: DatasetPreviewResponse;
};

export default function DatasetPreview({ dataset }: DatasetPreviewProps) {
  return (
    <div className="min-w-0 space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Filename" value={dataset.filename} />
        <StatCard label="Kind" value={dataset.kind} />
        <StatCard label="Rows" value={String(dataset.rows)} />
        <StatCard label="Columns" value={String(dataset.columns)} />
      </div>

      <div className="min-w-0 rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-5 py-4">
          <h2 className="text-lg font-semibold">Preview</h2>
          <p className="text-sm text-slate-500">
            First {dataset.preview.length} rows of the uploaded dataset
          </p>
        </div>

        <div className="max-w-full overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                {dataset.columnNames.map((col) => (
                  <th
                    key={col}
                    className="border-b border-slate-200 px-4 py-3 text-left font-medium text-slate-700 align-top"
                  >
                    <div className="max-w-[220px] whitespace-pre-line break-words leading-5">
                      {wrapEveryNCharacters(col, 20)}
                    </div>
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
                      className="whitespace-nowrap border-b border-slate-100 px-4 py-3 align-top text-slate-700"
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
    <div className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-2 break-words text-base font-semibold text-slate-900">
        {value}
      </div>
    </div>
  );
}

function wrapEveryNCharacters(text: string, chunkSize: number): string {
  if (!text) return "";

  const chunks: string[] = [];
  for (let i = 0; i < text.length; i += chunkSize) {
    chunks.push(text.slice(i, i + chunkSize));
  }

  return chunks.join("\n");
}