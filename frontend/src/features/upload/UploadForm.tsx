import { useState } from "react";
import type { DatasetKind } from "../../lib/types";

type UploadFormProps = {
  kind: DatasetKind;
  loading: boolean;
  onKindChange: (kind: DatasetKind) => void;
  onFileSubmit: (
    file: File,
    kind: "protein" | "phospho" | "phosprot",
    inputValue: string
  ) => void;
  onPeptideSubmit: (file: File, inputValue: string) => void;
};

export default function UploadForm({
  kind,
  loading,
  onKindChange,
  onFileSubmit,
  onPeptideSubmit,
}: UploadFormProps) {
  const [file, setFile] = useState<File | null>(null);
  const [tableInputValue, setTableInputValue] = useState("");
  const [peptideInputValue, setPeptideInputValue] = useState("");

  const isTableKind = kind === "protein" || kind === "phospho" || kind === "phosprot";
  const isPeptide = kind === "peptide";

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4">
        <h2 className="text-lg font-semibold">Upload Dataset</h2>
      </div>

      <div className="grid gap-4">
        <div className="max-w-sm">
          <label htmlFor="upload-dataset-kind" className="mb-2 block text-sm font-medium text-slate-700">
            Dataset type
          </label>
          <select
            id="upload-dataset-kind"
            value={kind}
            onChange={(e) => {
              setFile(null);
              setTableInputValue("");
              setPeptideInputValue("");
              onKindChange(e.target.value as DatasetKind);
            }}
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
              <label htmlFor="upload-table-file" className="mb-2 block text-sm font-medium text-slate-700">
                File
              </label>
              <input
                key={`upload-file-${kind}`}
                id="upload-table-file"
                type="file"
                accept=".csv,.tsv,.txt,.xlsx,.parquet"
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  setTableInputValue(e.target.value);
                }}
                className="block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
              />
            </div>

            <button
              onClick={() => file && onFileSubmit(file, kind, tableInputValue)}
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
              <label htmlFor="upload-peptide-file" className="mb-2 block text-sm font-medium text-slate-700">
                File
              </label>
              <input
                key="upload-file-peptide"
                id="upload-peptide-file"
                type="file"
                accept=".csv,.tsv,.txt,.xlsx,.parquet"
                onChange={(e) => {
                  setFile(e.target.files?.[0] ?? null);
                  setPeptideInputValue(e.target.value);
                }}
                className="block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm"
              />
            </div>

            <button
              onClick={() => file && onPeptideSubmit(file, peptideInputValue)}
              disabled={!file || loading}
              className="w-full rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50 lg:w-auto"
            >
              {loading ? "Uploading..." : "Upload"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
