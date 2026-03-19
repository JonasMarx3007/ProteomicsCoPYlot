import type { DatasetKind } from "../../lib/types";

type UploadFormProps = {
  file: File | null;
  kind: DatasetKind;
  loading: boolean;
  onFileChange: (file: File | null) => void;
  onKindChange: (kind: DatasetKind) => void;
  onSubmit: () => void;
};

export default function UploadForm({
  file,
  kind,
  loading,
  onFileChange,
  onKindChange,
  onSubmit,
}: UploadFormProps) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Upload dataset</h2>
        <p className="text-sm text-slate-500">
          Supported formats: CSV, TSV, TXT, XLSX, Parquet
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)_auto] lg:items-end">
        <div className="min-w-0">
          <label className="mb-2 block text-sm font-medium text-slate-700">
            Dataset type
          </label>
          <select
            value={kind}
            onChange={(e) => onKindChange(e.target.value as DatasetKind)}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 outline-none focus:border-slate-900"
          >
            <option value="protein">Protein</option>
            <option value="phospho">Phospho</option>
          </select>
        </div>

        <div className="min-w-0">
          <label className="mb-2 block text-sm font-medium text-slate-700">
            File
          </label>
          <input
            type="file"
            accept=".csv,.tsv,.txt,.xlsx,.parquet"
            onChange={(e) => onFileChange(e.target.files?.[0] ?? null)}
            className="block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
          />
          {file && (
            <div className="mt-2 truncate text-sm text-slate-500">
              {file.name}
            </div>
          )}
        </div>

        <button
          onClick={onSubmit}
          disabled={!file || loading}
          className="w-full rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 lg:w-auto"
        >
          {loading ? "Uploading..." : "Upload"}
        </button>
      </div>
    </div>
  );
}