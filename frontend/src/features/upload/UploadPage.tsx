import { useState } from "react";
import { uploadDataset } from "../../lib/api";
import type { DatasetKind, DatasetPreviewResponse } from "../../lib/types";
import UploadForm from "./UploadForm";
import DatasetPreview from "./DatasetPreview";

export default function UploadPage() {
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <h1>Upload dataset</h1>

      <UploadForm
        file={file}
        kind={kind}
        loading={loading}
        onFileChange={setFile}
        onKindChange={setKind}
        onSubmit={handleUpload}
      />

      {error && (
        <div style={{ color: "crimson", marginBottom: 16 }}>
          {error}
        </div>
      )}

      {result && <DatasetPreview dataset={result} />}
    </div>
  );
}