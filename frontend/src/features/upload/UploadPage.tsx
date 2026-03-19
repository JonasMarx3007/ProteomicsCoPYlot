import { useState } from "react";
import { uploadDataset } from "../../lib/api";
import type { DatasetKind, DatasetPreviewResponse } from "../../lib/types";
import UploadForm from "./UploadForm";
import DatasetPreview from "./DatasetPreview";

type UploadPageProps = {
  onDatasetUploaded?: (dataset: DatasetPreviewResponse) => void;
};

export default function UploadPage({ onDatasetUploaded }: UploadPageProps) {
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<DatasetKind>("protein");
  const [result, setResult] = useState<DatasetPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleUpload() {
    if (!file) return;

    try {
      setLoading(true);
      setError(null);
      const uploaded = await uploadDataset(file, kind);
      setResult(uploaded);
      onDatasetUploaded?.(uploaded);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <UploadForm
        file={file}
        kind={kind}
        loading={loading}
        onFileChange={setFile}
        onKindChange={setKind}
        onSubmit={handleUpload}
      />

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {result ? (
        <DatasetPreview dataset={result} />
      ) : (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          No dataset uploaded yet.
        </div>
      )}
    </div>
  );
}