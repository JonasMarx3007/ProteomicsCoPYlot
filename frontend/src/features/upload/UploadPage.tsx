import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getCurrentDatasets,
  savePeptidePath,
  uploadPeptideFile,
  uploadDataset,
} from "../../lib/api";
import { IS_VIEWER_MODE } from "../../lib/appMode";
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
  readOnly?: boolean;
};

type LocalFile = File & {
  path?: string;
};

function resolveSelectedPeptidePath(file: File, inputValue: string): string | null {
  const localPath = (file as LocalFile).path?.trim();
  if (localPath) {
    return localPath;
  }

  const raw = inputValue.trim();
  if (raw && !raw.toLowerCase().includes("fakepath")) {
    return raw;
  }

  return null;
}

export default function UploadPage({ onDatasetUploaded, readOnly = false }: UploadPageProps) {
  const [kind, setKind] = useState<DatasetKind>("protein");
  const [current, setCurrent] = useState<CurrentDatasetsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [viewerRefreshAttempts, setViewerRefreshAttempts] = useState(0);

  const refreshCurrentDatasets = useCallback(async () => {
    const data = await getCurrentDatasets();
    setCurrent(data);
    return data;
  }, []);

  useEffect(() => {
    refreshCurrentDatasets().catch((err) => {
      // Do not show a blocking error on passive initial load.
      setCurrent({ protein: null, phospho: null, phosprot: null, peptide: null });
      console.warn(err);
    });
  }, [refreshCurrentDatasets]);

  const displayedDataset = useMemo(() => {
    if (!current || kind === "peptide") return null;
    return current[kind];
  }, [current, kind]);

  useEffect(() => {
    onDatasetUploaded?.(displayedDataset);
  }, [displayedDataset, onDatasetUploaded]);

  useEffect(() => {
    if (!readOnly || !IS_VIEWER_MODE) return;

    const hasAnyDataset =
      Boolean(current?.protein) ||
      Boolean(current?.phospho) ||
      Boolean(current?.phosprot) ||
      Boolean(current?.peptide);
    if (hasAnyDataset) return;
    if (viewerRefreshAttempts >= 20) return;

    const timer = window.setTimeout(() => {
      setViewerRefreshAttempts((value) => value + 1);
      refreshCurrentDatasets().catch(() => {
        // keep current fallback state if backend is still booting
      });
    }, 700);
    return () => window.clearTimeout(timer);
  }, [current, readOnly, viewerRefreshAttempts, refreshCurrentDatasets]);

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

  async function handlePeptideSubmit(file: File, inputValue: string) {
    try {
      setLoading(true);
      setError(null);

      const resolvedPath = resolveSelectedPeptidePath(file, inputValue);
      if (resolvedPath) {
        await savePeptidePath(resolvedPath);
      } else {
        await uploadPeptideFile(file);
      }
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
      {readOnly ? (
        <section className="space-y-3 rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3">
          <div className="text-sm text-sky-800">
            Viewer mode is read-only. Data is loaded from <code>viewer_config.json</code>.
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700">
              Dataset level preview
            </label>
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as DatasetKind)}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 lg:max-w-sm"
            >
              <option value="protein">Protein</option>
              <option value="phospho">Phospho</option>
              <option value="phosprot">Phosphoprotein</option>
              <option value="peptide">Peptide</option>
            </select>
          </div>
        </section>
      ) : (
        <UploadForm
          kind={kind}
          loading={loading}
          onKindChange={setKind}
          onFileSubmit={handleFileSubmit}
          onPeptideSubmit={handlePeptideSubmit}
        />
      )}

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
            Peptide datasets store only the selected local file path. No preview is shown.
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
