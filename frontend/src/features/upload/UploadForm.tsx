import { useEffect, useState } from "react";
import type { DatasetKind } from "../../lib/types";

type UploadFormProps = {
  kind: DatasetKind;
  loading: boolean;
  onKindChange: (kind: DatasetKind) => void;
  onFileSubmit: (file: File, kind: "protein" | "phospho" | "phosprot") => void;
  onPeptideSubmit: (path: string) => void;
};

export default function UploadForm({
  kind,
  loading,
  onKindChange,
  onFileSubmit,
  onPeptideSubmit,
}: UploadFormProps) {
  const [file, setFile] = useState<File | null>(null);
  const [peptidePath, setPeptidePath] = useState("");

  const isTableKind = kind === "protein" || kind === "phospho" || kind === "phosprot";
  const isPeptide = kind === "peptide";

  useEffect(() => {
    setFile(null);
    setPeptidePath("");
  }, [kind]);

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Upload Dataset</h2>
        <p className="text-sm text-slate-500">
          Protein, phospho, and phosphoprotein datasets are uploaded and previewed. Peptide stores
          only the absolute file path.
        </p>
      </div>

      <div className="grid gap-4">
        <div className="max-w-sm">
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
            <option value="phosprot">Phosphoprotein</option>
            <option value="peptide">Peptide</option>
          </select>
        </div>

        {isTableKind && (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <div className="min-w-0">
              <label className="mb-2 block text-sm font-medium text-slate-700">
                File
              </label>
              <input
                key={`upload-file-${kind}`}
                type="file"
                accept=".csv,.tsv,.txt,.xlsx,.parquet"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
              />
            </div>

            <button
              onClick={() => file && onFileSubmit(file, kind)}
              disabled={!file || loading}
              className="w-full rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 lg:w-auto"
            >
              {loading ? "Uploading..." : "Upload"}
            </button>
          </div>
        )}

        {isPeptide && (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
            <div className="min-w-0">
              <label className="mb-2 block text-sm font-medium text-slate-700">
                Absolute file path
              </label>
              <input
                type="text"
                value={peptidePath}
                onChange={(e) => setPeptidePath(e.target.value)}
                placeholder="C:\Data\my_peptide_file.tsv"
                className="block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
              />
            </div>

            <button
              onClick={() => onPeptideSubmit(peptidePath)}
              disabled={!peptidePath.trim() || loading}
              className="w-full rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 lg:w-auto"
            >
              {loading ? "Saving..." : "Save Path"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
