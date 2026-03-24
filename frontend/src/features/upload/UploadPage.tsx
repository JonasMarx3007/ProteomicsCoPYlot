import { useEffect, useMemo, useState } from "react";
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
  const [current, setCurrent] = useState<CurrentDatasetsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshCurrentDatasets() {
    const data = await getCurrentDatasets();
    setCurrent(data);
    return data;
  }

  useEffect(() => {
    refreshCurrentDatasets().catch((err) => {
      // Do not show a blocking error on passive initial load.
      setCurrent({ protein: null, phospho: null, phosprot: null, peptide: null });
      console.warn(err);
    });
  }, []);

  const displayedDataset = useMemo(() => {
    if (!current || kind === "peptide") return null;
    return current[kind];
  }, [current, kind]);

  useEffect(() => {
    onDatasetUploaded?.(displayedDataset);
  }, [displayedDataset, onDatasetUploaded]);

  async function handleFileSubmit(
    file: File,
    uploadKind: "protein" | "phospho" | "phosprot"
  ) {
    try {
      setLoading(true);
      setError(null);

      await uploadDataset(file, uploadKind);
      const updated = await refreshCurrentDatasets();

      onDatasetUploaded?.(updated[uploadKind]);
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
      await refreshCurrentDatasets();

      onDatasetUploaded?.(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Saving path failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <UploadForm
        kind={kind}
        loading={loading}
        onKindChange={setKind}
        onFileSubmit={handleFileSubmit}
        onPeptideSubmit={handlePeptideSubmit}
      />

      <CurrentDatasetsPanel current={current} />

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {kind !== "peptide" && displayedDataset ? (
        <DatasetPreview dataset={displayedDataset} />
      ) : kind === "peptide" ? (
        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <h2 className="text-lg font-semibold text-slate-900">Preview</h2>
          <p className="mt-2 text-sm text-slate-500">
            Peptide datasets store only the absolute file path. No preview is shown.
          </p>
        </div>
      ) : (
        <div className="rounded-2xl border border-slate-200 bg-white p-6">
          <h2 className="text-lg font-semibold text-slate-900">Preview</h2>
          <p className="mt-2 text-sm text-slate-500">
            No {kind} dataset uploaded yet.
          </p>
        </div>
      )}
    </div>
  );
}
