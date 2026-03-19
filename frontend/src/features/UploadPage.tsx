import { useState } from "react";

type DatasetKind = "protein" | "phospho";

type DatasetPreviewResponse = {
  datasetId: string;
  filename: string;
  kind: DatasetKind;
  format: string;
  rows: number;
  columns: number;
  columnNames: string[];
  preview: Record<string, unknown>[];
};

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<DatasetKind>("protein");
  const [result, setResult] = useState<DatasetPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onUpload() {
    if (!file) return;

    setLoading(true);
    setError(null);

    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);

    try {
      const res = await fetch("http://localhost:8000/api/datasets/upload", {
        method: "POST",
        body: form,
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");

      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-2xl font-semibold">Upload dataset</h1>

      <div className="flex gap-3 items-center">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as DatasetKind)}
          className="border rounded px-3 py-2"
        >
          <option value="protein">Protein</option>
          <option value="phospho">Phospho</option>
        </select>

        <input
          type="file"
          accept=".csv,.tsv,.txt,.xlsx,.parquet"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />

        <button
          onClick={onUpload}
          disabled={!file || loading}
          className="border rounded px-4 py-2"
        >
          {loading ? "Uploading..." : "Upload"}
        </button>
      </div>

      {error && <div className="text-red-600">{error}</div>}

      {result && (
        <div className="space-y-4">
          <div className="border rounded p-4">
            <div><strong>File:</strong> {result.filename}</div>
            <div><strong>Kind:</strong> {result.kind}</div>
            <div><strong>Rows:</strong> {result.rows}</div>
            <div><strong>Columns:</strong> {result.columns}</div>
          </div>

          <div className="overflow-auto border rounded">
            <table className="min-w-full text-sm">
              <thead>
                <tr>
                  {result.columnNames.map((col) => (
                    <th key={col} className="border-b px-3 py-2 text-left">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.preview.map((row, i) => (
                  <tr key={i}>
                    {result.columnNames.map((col) => (
                      <td key={col} className="border-b px-3 py-2">
                        {String(row[col] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}