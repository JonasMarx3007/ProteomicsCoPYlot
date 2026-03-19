import { useEffect, useState } from "react";
import {
  getCurrentDatasets,
  savePeptidePath,
  uploadDataset,
} from "../../lib/api";
import type {
  CurrentDatasetsResponse,
  DatasetKind,
  DatasetPreviewResponse,
} from "../../lib/types";
import CurrentDatasetsPanel from "./CurrentDatasetsPanel";
import DatasetPreview from "./DatasetPreview";
import UploadForm from "./UploadForm";

type UploadPageProps = {
  onDatasetUploaded?: (dataset: DatasetPreviewResponse | null) => void;
};

export default function UploadPage({ onDatasetUploaded }: UploadPageProps) {
  const [kind, setKind] = useState<DatasetKind>("protein");
  const [result, setResult] = useState<DatasetPreviewResponse | null>(null);
  const [current, setCurrent] = useState<CurrentDatasetsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshCurrentDatasets() {
    const data = await getCurrentDatasets();
    setCurrent(data);
  }

  useEffect(() => {
    refreshCurrentDatasets().catch((err) => {
      setError(err instanceof Error ? err.message : "Failed to load datasets");
    });
  }, []);

  async function handleFileSubmit(
    file: File,
    uploadKind: "protein" | "phospho"
  ) {
    try {
      setLoading(true);
      setError(null);
      const uploaded = await uploadDataset(file, uploadKind);
      setResult(uploaded);
      onDatasetUploaded?.(uploaded);
      await refreshCurrentDatasets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setLoading(false);
    }
  }

  async function handlePeptideSubmit(path: string) {
    try {
      setLoading(true);
      setError(null);
      await savePeptidePath(path);
      setResult(null);
      onDatasetUploaded?.(null);
      await refreshCurrentDatasets();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Saving path failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <CurrentDatasetsPanel current={current} />

      <UploadForm
        kind={kind}
        loading={loading}
        onKindChange={setKind}
        onFileSubmit={handleFileSubmit}
        onPeptideSubmit={handlePeptideSubmit}
      />

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {kind !== "peptide" && result ? (
        <DatasetPreview dataset={result} />
      ) : kind === "peptide" ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          Peptide datasets store only the absolute file path. No preview is shown.
        </div>
      ) : (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          No dataset uploaded yet.
        </div>
      )}
    </div>
  );
}