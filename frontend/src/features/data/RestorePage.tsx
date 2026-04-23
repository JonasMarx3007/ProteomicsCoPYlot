import { useMemo, useState } from "react";
import { importRestoreState } from "../../lib/api";
import { markSkipBrowserSessionResetOnce } from "../../lib/datasetAvailability";
import type { RestoreImportResponse, RestoreMissingFile } from "../../lib/types";

type LocalFile = File & {
  path?: string;
};

type RestoreReplacement = {
  packageName: string;
  kind: "protein" | "phospho" | "phosprot" | "peptide";
  file: File;
  sourcePath: string | null;
};

type SelectedReplacement = {
  file: File;
  sourcePath: string | null;
};

type Props = {
  onApplyUiState: (state: Record<string, unknown>) => void;
  onQuickSave: () => Promise<void>;
  onQuickSaveAs: () => Promise<void>;
  onOpenStateFile: (() => Promise<File | null>) | null;
  currentSaveFileName: string | null;
};

function missingKey(item: RestoreMissingFile): string {
  return `${item.packageName}::${item.kind}`;
}

function resolveSelectedLocalPath(file: File, inputValue: string): string | null {
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

export default function RestorePage({
  onApplyUiState,
  onQuickSave,
  onQuickSaveAs,
  onOpenStateFile,
  currentSaveFileName,
}: Props) {
  const [stateFile, setStateFile] = useState<File | null>(null);
  const [missingFiles, setMissingFiles] = useState<RestoreMissingFile[]>([]);
  const [replacementFiles, setReplacementFiles] = useState<Record<string, SelectedReplacement | null>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);

  const replacementsReady = useMemo(() => {
    if (missingFiles.length === 0) return true;
    return missingFiles.every((item) => Boolean(replacementFiles[missingKey(item)]));
  }, [missingFiles, replacementFiles]);

  async function handleSaveState() {
    try {
      setBusy(true);
      setError(null);
      setInfo(null);
      await onQuickSave();
      setInfo("Save state written successfully.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export save state.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveStateAs() {
    try {
      setBusy(true);
      setError(null);
      setInfo(null);
      await onQuickSaveAs();
      setInfo("Save state written to the selected file.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export save state.");
    } finally {
      setBusy(false);
    }
  }

  async function handleOpenStateFile() {
    if (!onOpenStateFile) return;
    try {
      setBusy(true);
      setError(null);
      const file = await onOpenStateFile();
      if (!file) return;
      setStateFile(file);
      setMissingFiles([]);
      setReplacementFiles({});
      setWarnings([]);
      setInfo(`Selected: ${file.name}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to open save state.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRestoreState() {
    if (!stateFile) {
      setError("Select a save state file first.");
      return;
    }
    try {
      setBusy(true);
      setError(null);
      setInfo(null);
      setWarnings([]);

      const replacements = missingFiles
        .map((item) => {
          const selected = replacementFiles[missingKey(item)] || null;
          if (!selected) return null;
          return {
            packageName: item.packageName,
            kind: item.kind,
            file: selected.file,
            sourcePath: selected.sourcePath,
          };
        })
        .filter((item): item is RestoreReplacement => Boolean(item));

      const response: RestoreImportResponse = await importRestoreState(stateFile, replacements);
      if (!response.ok) {
        setMissingFiles(response.missingFiles ?? []);
        setInfo("Some saved dataset paths are missing. Upload the listed files to finish restore.");
        return;
      }

      setMissingFiles([]);
      setReplacementFiles({});
      onApplyUiState(response.uiState ?? {});
      setWarnings(response.warnings ?? []);
      setInfo(
        `Restore complete. Datasets: ${response.restoredDatasets.length}, annotations: ${response.restoredAnnotations.length}. Reloading UI to rehydrate all module states...`
      );
      window.setTimeout(() => {
        markSkipBrowserSessionResetOnce();
        window.location.reload();
      }, 200);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore save state.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Save State</h2>
        <p className="mt-1 text-sm text-slate-600">
          Save a compact restore file containing backend state, metadata tables, and UI state.
        </p>
        {currentSaveFileName ? (
          <div className="mt-3 text-sm text-slate-600">Current save target: {currentSaveFileName}</div>
        ) : null}
        <div className="mt-4 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={handleSaveState}
            disabled={busy}
            className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Working..." : currentSaveFileName ? "Update Save State" : "Save State..."}
          </button>
          <button
            type="button"
            onClick={handleSaveStateAs}
            disabled={busy}
            className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Working..." : "Save State As..."}
          </button>
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Restore State</h2>
        <p className="mt-1 text-sm text-slate-600">
          Upload a save state file to restore datasets, annotations, and UI state.
        </p>
        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto_auto]">
          <input
            type="file"
            accept=".copylotstate,.bin,.json,.gz,application/octet-stream"
            onChange={(event) => {
              const file = event.target.files?.[0] ?? null;
              setStateFile(file);
              setMissingFiles([]);
              setReplacementFiles({});
              setWarnings([]);
              setInfo(file ? `Selected: ${file.name}` : null);
              setError(null);
            }}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-slate-900"
          />
          {onOpenStateFile ? (
            <button
              type="button"
              onClick={handleOpenStateFile}
              disabled={busy}
              className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "Working..." : "Open Save File..."}
            </button>
          ) : null}
          <button
            type="button"
            onClick={handleRestoreState}
            disabled={busy || !stateFile || (missingFiles.length > 0 && !replacementsReady)}
            className="rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? "Restoring..." : "Restore"}
          </button>
        </div>
      </section>

      {missingFiles.length > 0 ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-amber-900">Missing Files</h3>
          <p className="mt-1 text-sm text-amber-800">
            The saved absolute path was not available. Upload the missing dataset files below and run restore again.
          </p>
          <div className="mt-4 space-y-4">
            {missingFiles.map((item) => {
              const key = missingKey(item);
              return (
                <div key={key} className="rounded-xl border border-amber-300 bg-white p-4">
                  <div className="text-sm font-semibold text-slate-900">
                    {item.packageName} / {item.kind}
                  </div>
                  <div className="mt-1 text-xs text-slate-600">{item.message}</div>
                  {item.expectedPath ? (
                    <div className="mt-1 text-xs text-slate-500">Saved path: {item.expectedPath}</div>
                  ) : null}
                  {item.filename ? (
                    <div className="mt-1 text-xs text-slate-500">Saved filename: {item.filename}</div>
                  ) : null}
                  <input
                    type="file"
                    onChange={(event) => {
                      const file = event.target.files?.[0] ?? null;
                      setReplacementFiles((prev) => ({
                        ...prev,
                        [key]: file
                          ? {
                              file,
                              sourcePath: resolveSelectedLocalPath(file, event.target.value),
                            }
                          : null,
                      }));
                    }}
                    className="mt-3 w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 outline-none focus:border-slate-900"
                  />
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      {info ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
          {info}
        </section>
      ) : null}

      {warnings.length > 0 ? (
        <section className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {warnings.join(" ")}
        </section>
      ) : null}

      {error ? (
        <section className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </section>
      ) : null}
    </div>
  );
}
