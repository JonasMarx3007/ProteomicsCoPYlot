import type { DatasetPreviewResponse } from "../../lib/types";

type DatasetPreviewProps = {
  dataset: DatasetPreviewResponse;
};

const MAX_CELL_LENGTH = 20;
const COLUMN_WRAP_LENGTH = 20;

export default function DatasetPreview({ dataset }: DatasetPreviewProps) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-slate-900">Preview</h2>
        <p className="mt-1 text-sm text-slate-500">
          First {dataset.preview.length} rows of the selected {dataset.kind} dataset
        </p>
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <StatCard label="Filename" value={truncateText(dataset.filename, 30)} />
        <StatCard label="Rows" value={String(dataset.rows)} />
        <StatCard label="Columns" value={String(dataset.columns)} />
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-200">
        <table className="min-w-full table-fixed border-collapse text-sm">
          <thead className="bg-slate-50">
            <tr>
              {dataset.columnNames.map((col) => (
                <th
                  key={col}
                  className="border-b border-slate-200 px-3 py-2 text-left font-medium text-slate-700"
                >
                  <div className="whitespace-pre-line break-words">
                    {wrapEveryNCharacters(col, COLUMN_WRAP_LENGTH)}
                  </div>
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {dataset.preview.map((row, rowIndex) => (
              <tr key={rowIndex} className="odd:bg-white even:bg-slate-50/50">
                {dataset.columnNames.map((col) => {
                  const rawValue = String(row[col] ?? "");
                  const displayValue = truncateText(rawValue, MAX_CELL_LENGTH);

                  return (
                    <td
                      key={`${rowIndex}-${col}`}
                      className="border-b border-slate-100 px-3 py-2 align-top text-slate-600"
                      title={rawValue}
                    >
                      <div className="max-w-[20ch] overflow-hidden text-ellipsis whitespace-nowrap">
                        {displayValue}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-sm font-semibold text-slate-900" title={value}>
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

function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}…`;
}