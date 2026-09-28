import SummaryCard from "../../components/SummaryCard";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  aggregatePhosprot,
  createMetadataProfile,
  deleteMetadataProfile,
  detectAnnotationLog2Scale,
  downloadCurrentAnnotationFilteredData,
  downloadCurrentAnnotationMetadataData,
  downloadCurrentAnnotationSourceData,
  generatePeptideMetadata,
  generateAnnotation,
  getCurrentAnnotation,
  getCurrentDatasets,
  getCurrentPeptideMetadata,
  getNormalizationCapability,
  getPeptideOverview,
  getUploadedAnnotationMetadata,
  renameMetadataProfile,
  setActiveMetadataProfile,
  uploadAnnotationMetadata,
} from "../../lib/api";
import { subscribeDatasetStateChanged } from "../../lib/datasetEvents";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import type {
  AnnotationKind,
  AnnotationFilterConfig,
  AnnotationResultResponse,
  ConditionAssignment,
  CurrentDatasetsResponse,
  MetadataUploadResponse,
  MetadataAnnotationKind,
  NormalizationCapabilityResponse,
  PeptideMetadataResponse,
  PeptideOverviewResponse,
  PhosprotAggregationMode,
  PhosprotAggregationSource,
} from "../../lib/types";
import { NORMALIZATION_LABELS } from "../../lib/types";
import PreviewTable from "../../components/PreviewTable";

type ConditionDraft = {
  id: number;
  name: string;
  columns: string[];
};

type AnnotationPageKind = AnnotationKind | "peptide";

const DEFAULT_FILTER: AnnotationFilterConfig = {
  method: "at_least_n",
  minPresent: 0,
  minPercentage: 70,
  mode: "per_group",
  normalization: "none",
};

const PHOSPROT_MODE_DESCRIPTIONS: Record<PhosprotAggregationMode, string> = {
  robust_site_median:
    "Default: centre each site on log2 scale and take the protein median when at least 50% of its eligible sites have values, including imputed values. Coverage diagnostics count original observations only.",
  sum_propagate_na:
    "Sum the fixed eligible site set on linear scale; any missing eligible site makes that sample value missing.",
  sum_ignore_na:
    "Sum supplied site values on linear scale, including imputed values, while ignoring missing sites; inspect the exported observed-coverage diagnostics.",
  mean:
    "Take the linear-scale mean of supplied site values, including imputed values; changing site coverage can change the result.",
};

const ANNOTATION_MANAGER_VISIBILITY_KEY = "data.annotationManager.visible.v1";
const MAX_MANUAL_METADATA_PROFILES = 5;

export default function AnnotationPage() {
  const [kind, setKind] = useState<AnnotationPageKind>("protein");
  const [currentDatasets, setCurrentDatasets] = useState<CurrentDatasetsResponse | null>(
    null
  );
  const [conditions, setConditions] = useState<ConditionDraft[]>([
    { id: 1, name: "", columns: [] },
  ]);
  const [isLog2Transformed, setIsLog2Transformed] = useState(true);
  const scaleChosen = useRef(false);
  const scaleRequest = useRef(0);
  const [filterConfig, setFilterConfig] = useState<AnnotationFilterConfig>(DEFAULT_FILTER);
  // VSN is delegated to Bioconductor `vsn` via Rscript, so it is only offered
  // when R and the package are actually present rather than failing at run time.
  const [normalizationCapability, setNormalizationCapability] =
    useState<NormalizationCapabilityResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    getNormalizationCapability()
      .then((payload) => {
        if (!cancelled) setNormalizationCapability(payload);
      })
      .catch(() => {
        if (!cancelled) setNormalizationCapability(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const [result, setResult] = useState<AnnotationResultResponse | null>(null);
  const visibleWarnings = (result?.warnings ?? []).filter((warning) =>
    !/^(No normalization was applied\.|Median centering was applied globally|Quantile normalization was applied globally|VSN was applied globally|No phosphoprotein-level normalization was applied\.|Phosphosite-level normalization was )/.test(warning),
  );
  const [peptideOverview, setPeptideOverview] = useState<PeptideOverviewResponse | null>(null);
  const [peptideResult, setPeptideResult] = useState<PeptideMetadataResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metadataFile, setMetadataFile] = useState<File | null>(null);
  const [uploadedMetadata, setUploadedMetadata] = useState<MetadataUploadResponse | null>(null);
  const [uploadingMetadata, setUploadingMetadata] = useState(false);
  const [phosprotResult, setPhosprotResult] = useState<AnnotationResultResponse | null>(null);
  const [phosprotMode, setPhosprotMode] =
    useState<PhosprotAggregationMode>("robust_site_median");
  const [phosprotSource, setPhosprotSource] =
    useState<PhosprotAggregationSource>("non_imputed");
  const [phosprotBusy, setPhosprotBusy] = useState(false);
  const [downloadBusyKey, setDownloadBusyKey] = useState<string | null>(null);
  const [metadataProfileBusy, setMetadataProfileBusy] = useState(false);
  const [newMetadataProfileName, setNewMetadataProfileName] = useState("");
  const [renameMetadataProfileName, setRenameMetadataProfileName] = useState("");
  const [annotationManagerVisible, setAnnotationManagerVisible] = useState(() =>
    readPersistedUiState(ANNOTATION_MANAGER_VISIBILITY_KEY, false)
  );

  const activeDataset = currentDatasets?.[kind] ?? null;
  const activeDatasetSource =
    kind === "peptide"
      ? currentDatasets?.peptide?.path
      : currentDatasets?.[kind]?.sourcePath;
  const peptideDatasetAvailable = Boolean(currentDatasets?.peptide);
  const proteinDatasetAvailable = Boolean(currentDatasets?.protein);
  const peptideDatasetFilename = currentDatasets?.peptide?.filename;
  const peptideDatasetPath = currentDatasets?.peptide?.path;
  const proteinDatasetFilename = currentDatasets?.protein?.filename;
  const availableColumns =
    kind === "peptide"
      ? peptideOverview?.availableSamples ?? []
      : activeDataset?.columnNames ?? [];
  const availableKinds = useMemo<AnnotationPageKind[]>(() => {
    const kinds: AnnotationPageKind[] = [];
    if (currentDatasets?.protein) kinds.push("protein");
    if (currentDatasets?.phospho) kinds.push("phospho");
    if (currentDatasets?.phosprot) kinds.push("phosprot");
    if (!currentDatasets?.protein && currentDatasets?.peptide) kinds.push("peptide");
    return kinds;
  }, [currentDatasets]);
  const kindOptions = useMemo(
    () =>
      availableKinds.map((value) => ({
        value,
        label:
          value === "protein"
            ? "Protein"
            : value === "phospho"
              ? "Phospho"
              : value === "phosprot"
                ? "Phosphoprotein"
                : "Peptide",
      })),
    [availableKinds]
  );
  const metadataSupportedKind = kind === "protein" || kind === "phospho";
  const sharedMetadataKind: MetadataAnnotationKind | null =
    kind === "protein"
      ? "protein"
      : kind === "phospho" || kind === "phosprot"
        ? "phospho"
        : null;
  const usesSharedPhosphoMetadata = kind === "phosprot";
  const manualMetadataProfiles = useMemo(() => {
    const all = currentDatasets?.availableMetadataProfiles ?? ["Metadata"];
    const auto = new Set(currentDatasets?.autoGeneratedMetadataProfiles ?? []);
    const filtered = all.filter((name) => !auto.has(name));
    return filtered.length > 0 ? filtered : all;
  }, [currentDatasets?.availableMetadataProfiles, currentDatasets?.autoGeneratedMetadataProfiles]);
  const manualMetadataProfileCount = manualMetadataProfiles.length;
  const manualMetadataProfileLimitReached =
    manualMetadataProfileCount >= MAX_MANUAL_METADATA_PROFILES;

  async function refreshCurrent() {
    const datasets = await getCurrentDatasets();
    setCurrentDatasets(datasets);
    return datasets;
  }

  useEffect(() => {
    refreshCurrent().catch((err) => {
      setError(err instanceof Error ? err.message : "Failed to load datasets");
    });
  }, []);

  useEffect(() => {
    return subscribeDatasetStateChanged((snapshot) => {
      if (snapshot) {
        setCurrentDatasets(snapshot);
        return;
      }
      refreshCurrent().catch(() => {
        // keep current snapshot if transient refresh fails
      });
    });
  }, []);

  useEffect(() => {
    if (!peptideDatasetAvailable || proteinDatasetAvailable) {
      setPeptideOverview(null);
      return;
    }
    getPeptideOverview()
      .then((overview) => setPeptideOverview(overview))
      .catch((err) => {
        setPeptideOverview(null);
        setError(err instanceof Error ? err.message : "Failed to load peptide samples");
      });
  }, [
    peptideDatasetAvailable,
    proteinDatasetAvailable,
    peptideDatasetFilename,
    peptideDatasetPath,
    proteinDatasetFilename,
  ]);

  useEffect(() => {
    setRenameMetadataProfileName(currentDatasets?.activeMetadataProfile ?? "Metadata");
  }, [currentDatasets?.activeMetadataProfile]);

  useEffect(() => {
    const active = currentDatasets?.activeMetadataProfile ?? "";
    if (!active || manualMetadataProfiles.includes(active)) return;
    const fallback = manualMetadataProfiles[0];
    if (!fallback) return;
    handleMetadataProfileChange(fallback).catch(() => {
      // keep current profile if switch fails
    });
  }, [currentDatasets?.activeMetadataProfile, manualMetadataProfiles]);

  useEffect(() => {
    if (availableKinds.length === 0) return;
    if (!availableKinds.includes(kind)) {
      setKind(availableKinds[0]);
    }
  }, [availableKinds, kind]);

  useEffect(() => {
    scaleChosen.current = false;
    scaleRequest.current += 1;
    return () => { scaleRequest.current += 1; };
  }, [kind, activeDataset?.filename, activeDatasetSource, currentDatasets?.activePackage]);

  useEffect(() => {
    let cancelled = false;
    if (kind === "peptide") {
      setResult(null);
      getCurrentPeptideMetadata()
        .then((stored) => { if (!cancelled) setPeptideResult(stored); })
        .catch(() => { if (!cancelled) setPeptideResult(null); });
      return () => { cancelled = true; };
    }
    setPeptideResult(null);
    getCurrentAnnotation(kind)
      .then((stored) => {
        if (cancelled) return;
        setResult(stored);
        if (!scaleChosen.current) {
          scaleChosen.current = true;
          setIsLog2Transformed(stored.isLog2Transformed);
        }
        if (stored.filter) {
          setFilterConfig({ ...DEFAULT_FILTER, ...stored.filter });
        }
      })
      .catch(() => {
        if (cancelled) return;
        setResult(null);
        if (!scaleChosen.current) setIsLog2Transformed(true);
      });
    return () => { cancelled = true; };
  }, [
    kind,
    activeDataset?.filename,
    activeDatasetSource,
    currentDatasets?.activePackage,
    currentDatasets?.activeMetadataProfile,
  ]);

  useEffect(() => {
    getCurrentAnnotation("phosprot")
      .then((stored) => setPhosprotResult(stored))
      .catch(() => {
        setPhosprotResult(null);
      });
  }, [currentDatasets?.phosprot?.filename, currentDatasets?.activeMetadataProfile]);

  useEffect(() => {
    let cancelled = false;
    if (!sharedMetadataKind) {
      setUploadedMetadata(null);
      return;
    }
    getUploadedAnnotationMetadata(sharedMetadataKind)
      .then((metadata) => { if (!cancelled) setUploadedMetadata(metadata); })
      .catch(() => {
        if (!cancelled) setUploadedMetadata(null);
      });
    return () => { cancelled = true; };
  }, [sharedMetadataKind, currentDatasets?.activeMetadataProfile]);

  useEffect(() => {
    setMetadataFile(null);
  }, [kind, currentDatasets?.activeMetadataProfile]);

  function addCondition() {
    setConditions((prev) => [
      ...prev,
      { id: Date.now(), name: "", columns: [] },
    ]);
  }

  function removeCondition(id: number) {
    const next = conditions.filter((condition) => condition.id !== id);
    setConditions(next);
    updateLog2FromConditions(next);
  }

  function updateConditionName(id: number, name: string) {
    setConditions((prev) =>
      prev.map((condition) =>
        condition.id === id ? { ...condition, name } : condition
      )
    );
  }

  function updateConditionColumns(id: number, columns: string[]) {
    const next = conditions.map((condition) =>
      condition.id === id ? { ...condition, columns } : condition
    );
    setConditions(next);
    updateLog2FromConditions(next);
  }

  function updateLog2FromConditions(nextConditions: ConditionDraft[]) {
    scaleRequest.current += 1;
    if (kind === "peptide") return;
    const sampleColumns = Array.from(
      new Set(nextConditions.flatMap((condition) => condition.columns))
    );
    if (sampleColumns.length === 0) return;
    applyDetectedLog2State(sampleColumns);
  }

  async function applyDetectedLog2State(sampleColumns: string[]) {
    if (!activeDataset || kind === "peptide" || scaleChosen.current) return;
    const request = ++scaleRequest.current;
    try {
      const detection = await detectAnnotationLog2Scale({ kind, sampleColumns });
      if (request === scaleRequest.current && !scaleChosen.current && typeof detection.isLog2Transformed === "boolean") {
        setIsLog2Transformed(detection.isLog2Transformed);
      }
    } catch {
      // Detection is advisory; preserve the current manual checkbox state on failure.
    }
  }

  const requestConditions = useMemo<ConditionAssignment[]>(() => {
    return conditions
      .map((condition) => ({
        name: condition.name.trim(),
        columns: condition.columns,
      }))
      .filter((condition) => condition.name.length > 0 && condition.columns.length > 0);
  }, [conditions]);

  async function handleGenerate() {
    if (!activeDataset) {
      setError(`No ${kind} dataset loaded. Upload data first.`);
      return;
    }

    try {
      setLoading(true);
      setError(null);

      if (kind === "peptide") {
        const generated = await generatePeptideMetadata({
          conditions: requestConditions,
        });
        setPeptideResult(generated);
        return;
      }

      const generated = await generateAnnotation({
        kind,
        conditions: requestConditions,
        isLog2Transformed,
        filter:
          kind === "phosprot"
            ? { ...filterConfig, normalization: "none" }
            : filterConfig,
      });

      setResult(generated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate annotation");
    } finally {
      setLoading(false);
    }
  }

  async function handleMetadataUpload() {
    if (!activeDataset) {
      setError(`No ${kind} dataset loaded. Upload data first.`);
      return;
    }
    if (!metadataFile) {
      setError("Please choose a metadata file first.");
      return;
    }
    if (!metadataSupportedKind) {
      setError("Metadata upload is available only for protein and phospho datasets.");
      return;
    }

    try {
      setUploadingMetadata(true);
      setError(null);
      const uploaded = await uploadAnnotationMetadata(
        metadataFile,
        kind as MetadataAnnotationKind
      );
      setUploadedMetadata(uploaded);
      await refreshCurrent();
      await applyDetectedLog2State([]);
      setMetadataFile(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to upload metadata");
    } finally {
      setUploadingMetadata(false);
    }
  }

  async function handleAggregatePhosprot() {
    try {
      setPhosprotBusy(true);
      setError(null);
      const generated = await aggregatePhosprot(phosprotMode, phosprotSource);
      setPhosprotResult(generated);
      await refreshCurrent();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to aggregate phosphoprotein data"
      );
    } finally {
      setPhosprotBusy(false);
    }
  }

  async function handleDownloadFullData(
    kindToDownload: AnnotationKind,
    target: "filtered" | "metadata" | "source"
  ) {
    const busyKey = `${kindToDownload}:${target}`;
    try {
      setDownloadBusyKey(busyKey);
      setError(null);
      const { blob, filename } =
        target === "metadata"
          ? await downloadCurrentAnnotationMetadataData(kindToDownload)
          : target === "source"
            ? await downloadCurrentAnnotationSourceData(kindToDownload)
          : await downloadCurrentAnnotationFilteredData(kindToDownload);
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to download full annotation data");
    } finally {
      setDownloadBusyKey(null);
    }
  }

  async function handleCreateMetadataProfile() {
    const name = newMetadataProfileName.trim();
    if (!name) {
      setError("Please enter a metadata profile name.");
      return;
    }
    try {
      setMetadataProfileBusy(true);
      setError(null);
      const updated = await createMetadataProfile(name);
      setCurrentDatasets(updated);
      setNewMetadataProfileName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create metadata profile");
    } finally {
      setMetadataProfileBusy(false);
    }
  }

  async function handleMetadataProfileChange(nextProfile: string) {
    const name = nextProfile.trim();
    if (!name) return;
    try {
      setMetadataProfileBusy(true);
      setError(null);
      const updated = await setActiveMetadataProfile(name);
      setCurrentDatasets(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to switch metadata profile");
    } finally {
      setMetadataProfileBusy(false);
    }
  }

  async function handleRenameMetadataProfile() {
    const oldName = (currentDatasets?.activeMetadataProfile ?? "").trim();
    const newName = renameMetadataProfileName.trim();
    if (!oldName) {
      setError("No selected metadata profile.");
      return;
    }
    if (!newName) {
      setError("Please enter a new metadata profile name.");
      return;
    }
    try {
      setMetadataProfileBusy(true);
      setError(null);
      const updated = await renameMetadataProfile(oldName, newName);
      setCurrentDatasets(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to rename metadata profile");
    } finally {
      setMetadataProfileBusy(false);
    }
  }

  async function handleDeleteMetadataProfile() {
    const profileName = (currentDatasets?.activeMetadataProfile ?? "").trim();
    if (!profileName) {
      setError("No selected metadata profile.");
      return;
    }
    if (
      !window.confirm(
        `Delete metadata profile "${profileName}" and all automatic combinations that depend on it?`
      )
    ) {
      return;
    }
    try {
      setMetadataProfileBusy(true);
      setError(null);
      const updated = await deleteMetadataProfile(profileName);
      setCurrentDatasets(updated);
      setUploadedMetadata(null);
      setResult(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete metadata profile");
    } finally {
      setMetadataProfileBusy(false);
    }
  }

  function updateAnnotationManagerVisibility(visible: boolean) {
    setAnnotationManagerVisible(visible);
    writePersistedUiState(ANNOTATION_MANAGER_VISIBILITY_KEY, visible);
  }

  const canAggregatePhosprot =
    kind === "phospho" &&
    result !== null &&
    result.metadataRows > 0;
  const phosphoImputationAvailable =
    kind === "phospho" &&
    result?.imputation != null &&
    result.imputation.mode !== "none" &&
    result.imputation.applied === true &&
    (result.imputation.sampleCount ?? result.sampleCount) > 0;

  useEffect(() => {
    if (!phosphoImputationAvailable && phosprotSource === "imputed") {
      setPhosprotSource("non_imputed");
    }
  }, [phosphoImputationAvailable, phosprotSource]);

  return (
    <div className="space-y-6">
      {!annotationManagerVisible ? (
        <div className="flex justify-end">
          <button
            type="button"
            aria-expanded="false"
            onClick={() => updateAnnotationManagerVisibility(true)}
            className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
          >
            Show Annotation Manager
          </button>
        </div>
      ) : (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-lg font-semibold text-slate-900">Annotation Manager</h2>
            <button
              type="button"
              aria-expanded="true"
              onClick={() => updateAnnotationManagerVisibility(false)}
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
            >
              Hide Annotation Manager
            </button>
          </div>

          <div className="mt-4 grid gap-3 lg:grid-cols-3">
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="annotation-metadata">Selected metadata</label>
              <select id="annotation-metadata"
                value={currentDatasets?.activeMetadataProfile ?? "Metadata"}
                onChange={(event) => handleMetadataProfileChange(event.target.value)}
                disabled={metadataProfileBusy}
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
              >
                {manualMetadataProfiles.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="annotation-new-profile">New metadata profile</label>
              <div className="flex gap-2">
                <input id="annotation-new-profile"
                  type="text"
                  value={newMetadataProfileName}
                  onChange={(event) => setNewMetadataProfileName(event.target.value)}
                  placeholder="Metadata_2"
                  disabled={metadataProfileBusy || manualMetadataProfileLimitReached}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
                />
                <button
                  type="button"
                  onClick={handleCreateMetadataProfile}
                  disabled={metadataProfileBusy || manualMetadataProfileLimitReached}
                  className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
                >
                  Create
                </button>
              </div>
              <p className="mt-1 text-xs text-slate-500">
                {manualMetadataProfileCount}/{MAX_MANUAL_METADATA_PROFILES} manual profiles
              </p>
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="annotation-rename-profile">Rename selected metadata</label>
              <div className="flex gap-2">
                <input id="annotation-rename-profile"
                  type="text"
                  value={renameMetadataProfileName}
                  onChange={(event) => setRenameMetadataProfileName(event.target.value)}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
                />
                <button
                  type="button"
                  onClick={handleRenameMetadataProfile}
                  disabled={metadataProfileBusy}
                  className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100 disabled:opacity-50"
                >
                  Rename
                </button>
                <button
                  type="button"
                  onClick={handleDeleteMetadataProfile}
                  disabled={metadataProfileBusy}
                  className="rounded-xl border border-red-300 bg-white px-3 py-2 text-sm text-red-700 transition hover:bg-red-50 disabled:opacity-50"
                >
                  Delete
                </button>
              </div>
            </div>
          </div>
        </section>
      )}

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">Data Annotation</h2>

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="annotation-level">
              Dataset level
            </label>
            <select id="annotation-level"
              value={kindOptions.length === 0 ? "" : kind}
              onChange={(e) => setKind(e.target.value as AnnotationPageKind)}
              disabled={kindOptions.length === 0}
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
            >
              {kindOptions.length === 0 ? (
                <option value="">No dataset available</option>
              ) : (
                kindOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))
              )}
            </select>
          </div>

          <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm">
            <div className="font-medium text-slate-700">Current dataset</div>
            {activeDataset ? (
              <div className="mt-2 space-y-1 text-slate-600">
                <div className="truncate" title={activeDataset.filename}>
                  {activeDataset.filename}
                </div>
                <div>
                  {kind === "peptide" && peptideOverview
                    ? `${peptideOverview.rows} rows, ${peptideOverview.columns} columns`
                    : `${activeDataset.rows} rows, ${activeDataset.columns} columns`}
                </div>
              </div>
            ) : (
              <div className="mt-2 text-slate-500">No dataset loaded.</div>
            )}
          </div>
        </div>

        {kind !== "peptide" ? (
          <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <label className="inline-flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={isLog2Transformed}
                onChange={(e) => {
                  scaleChosen.current = true;
                  scaleRequest.current += 1;
                  setIsLog2Transformed(e.target.checked);
                }}
              />
              Dataset is already log2 transformed
            </label>
          </div>
        ) : (
          <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
            No protein dataset is loaded. Peptide plots will use the condition mapping from
            the unique peptide file names below.
          </div>
        )}

        {kindOptions.length === 0 ? (
          <div className="mt-4 rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
            Upload a protein, phospho, phosphoprotein, or peptide dataset in the Data tab before annotation.
          </div>
        ) : null}

        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-4">
          <div className="text-sm font-medium text-slate-700">Uploaded Metadata (Optional)</div>
          {kind === "peptide" ? (
            <div className="mt-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
              Peptide-only annotation is generated from the unique file names in the loaded
              peptide report. Assign them to conditions below.
            </div>
          ) : metadataSupportedKind ? (
            <>
              <p className="mt-1 text-sm text-slate-600">
                If a metadata file is uploaded for this level, it overrides UI condition mapping during annotation generation.
              </p>
              <div className="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="annotation-metadata-file">Metadata file</label>
                  <input id="annotation-metadata-file"
                    key={`annotation-metadata-${kind}`}
                    type="file"
                    accept=".csv,.tsv,.txt,.xlsx,.parquet"
                    onChange={(e) => setMetadataFile(e.target.files?.[0] ?? null)}
                    disabled={!activeDataset}
                    className="block w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm disabled:cursor-not-allowed disabled:bg-slate-100"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleMetadataUpload}
                  disabled={!activeDataset || !metadataFile || uploadingMetadata}
                  className="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {uploadingMetadata ? "Uploading..." : "Upload Metadata"}
                </button>
              </div>

              {uploadedMetadata ? (
                <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                  {uploadedMetadata.profileNames.length > 1 ? (
                    <>
                      Split {uploadedMetadata.filename} into profiles{" "}
                      <span className="font-medium">{uploadedMetadata.profileNames.join(", ")}</span>
                      {` with ${uploadedMetadata.autoGeneratedProfileCount} automatic combinations.`}
                    </>
                  ) : (
                    <>
                      Using uploaded metadata file: {uploadedMetadata.filename} ({uploadedMetadata.rows} rows) in profile{" "}
                      <span className="font-medium">{uploadedMetadata.profileName}</span>
                    </>
                  )}
                </div>
              ) : (
                <div className="mt-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                  No uploaded metadata for this dataset level.
                </div>
              )}
            </>
          ) : usesSharedPhosphoMetadata ? (
            <>
              <p className="mt-1 text-sm text-slate-600">
                Phosphoprotein annotation reuses the uploaded phospho metadata from the active metadata profile. The phosphoprotein pipeline is still started separately here.
              </p>
              {uploadedMetadata ? (
                <div className="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                  Using shared phospho metadata file: {uploadedMetadata.filename} ({uploadedMetadata.rows} rows) in profile{" "}
                  <span className="font-medium">{uploadedMetadata.profileName}</span>
                </div>
              ) : (
                <div className="mt-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                  No shared phospho metadata is uploaded for the active metadata profile. Use condition mapping below, or upload metadata while the dataset level is set to phospho.
                </div>
              )}
            </>
          ) : (
            <div className="mt-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
              Metadata file upload is not used for phosphoprotein-level annotation. Use condition mapping below.
            </div>
          )}
        </div>

      </section>

      <details open={!uploadedMetadata || kind === "peptide"} className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <summary className="cursor-pointer text-lg font-semibold text-slate-900">Manual Condition Mapping</summary>
        {uploadedMetadata && kind !== "peptide" ? <p className="mt-3 text-sm text-slate-600">
          Uploaded metadata supplies the conditions. The manual settings below are retained but are not used while that metadata is active.
        </p> : null}

        <div className="mt-4 space-y-4">
          {conditions.map((condition) => (
            <div key={condition.id} className="rounded-xl border border-slate-200 p-4">
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]">
                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor={`condition-name-${condition.id}`}>
                    Condition name
                  </label>
                  <input id={`condition-name-${condition.id}`}
                    type="text"
                    value={condition.name}
                    onChange={(e) => updateConditionName(condition.id, e.target.value)}
                    placeholder="Control"
                    className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900"
                  />
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor={`condition-columns-${condition.id}`}>
                    {kind === "peptide" ? "Peptide file names" : "Sample columns"}
                  </label>
                  <div className="overflow-x-auto rounded-xl border border-slate-300">
                    <select id={`condition-columns-${condition.id}`}
                      multiple
                      value={condition.columns}
                      size={Math.max(4, Math.min(10, availableColumns.length || 4))}
                      onChange={(e) =>
                        updateConditionColumns(
                          condition.id,
                          Array.from(e.target.selectedOptions).map((option) => option.value)
                        )
                      }
                      className="min-w-full w-max border-0 px-3 py-2 text-sm outline-none"
                    >
                      {availableColumns.map((column) => (
                        <option key={column} value={column} className="whitespace-nowrap">
                          {column}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="self-end">
                  <button
                    type="button"
                    onClick={() => removeCondition(condition.id)}
                    className="rounded-xl border border-red-300 bg-white px-3 py-2 text-sm text-red-700 transition hover:bg-red-50"
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-4">
          <button
            type="button"
            onClick={addCondition}
            className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
          >
            Add condition
          </button>
          {kind === "peptide" ? (
            <button
              type="button"
              onClick={handleGenerate}
              disabled={!activeDataset || loading}
              className="ml-3 rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? "Generating..." : "Generate Peptide Annotation"}
            </button>
          ) : null}
        </div>
      </details>

      {kind === "peptide" && error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      ) : null}

      {kind !== "peptide" ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Filter Settings</h3>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="annotation-filter-method">
              Filter method
            </label>
            <select id="annotation-filter-method"
              value={filterConfig.method}
              onChange={(e) =>
                setFilterConfig((prev) => ({
                  ...prev,
                  method: e.target.value as AnnotationFilterConfig["method"],
                }))
              }
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
            >
              <option value="at_least_n">At least N values</option>
              <option value="percentage">Percentage</option>
            </select>
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="annotation-minimum">
              {filterConfig.method === "percentage"
                ? "Minimum completeness (%)"
                : "Minimum valid values"}
            </label>
            {filterConfig.method === "percentage" ? (
              <input
                type="text"
                lang="en-US"
                inputMode="decimal"
                id="annotation-minimum"
                value={String(filterConfig.minPercentage)}
                onChange={(e) => {
                  const value = Number(e.target.value.replace(",", "."));
                  setFilterConfig((prev) => ({
                    ...prev,
                    minPercentage: Number.isFinite(value)
                      ? Math.min(100, Math.max(0, value))
                      : 0,
                  }));
                }}
                className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900"
              />
            ) : (
              <input
                type="text"
                lang="en-US"
                inputMode="numeric"
                id="annotation-minimum"
                value={String(filterConfig.minPresent)}
                onChange={(e) =>
                  setFilterConfig((prev) => ({
                    ...prev,
                    minPresent: Math.max(0, Math.floor(Number(e.target.value) || 0)),
                  }))
                }
                className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-900"
              />
            )}
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="annotation-filter-scope">
              Scope
            </label>
            <select id="annotation-filter-scope"
              value={filterConfig.mode}
              onChange={(e) =>
                setFilterConfig((prev) => ({
                  ...prev,
                  mode: e.target.value as AnnotationFilterConfig["mode"],
                }))
              }
              className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
            >
              <option value="per_group">Each group</option>
              <option value="in_at_least_one_group">At least one group</option>
              <option value="overall">Overall</option>
            </select>
          </div>
          {kind === "phosprot" ? (
            <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 text-sm text-sky-800">
              Phosphoprotein values retain the normalization applied at phosphosite level
              before collapse. No second normalization is applied here.
            </div>
          ) : (
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="annotation-normalization">
                Normalization
              </label>
              <select id="annotation-normalization"
                value={filterConfig.normalization ?? "none"}
                onChange={(e) =>
                  setFilterConfig((prev) => ({
                    ...prev,
                    normalization: e.target.value as AnnotationFilterConfig["normalization"],
                  }))
                }
                className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
              >
                <option value="none">{NORMALIZATION_LABELS.none}</option>
                <option value="median">{NORMALIZATION_LABELS.median}</option>
                <option value="quantile">{NORMALIZATION_LABELS.quantile}</option>
                {normalizationCapability?.vsnAvailable ? (
                  <option value="vsn">{NORMALIZATION_LABELS.vsn}</option>
                ) : null}
              </select>
            </div>
          )}
        </div>

        <div className="mt-5">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={!activeDataset || loading}
            className="rounded-xl bg-slate-900 px-5 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Generating..." : "Generate Annotation"}
          </button>
        </div>

        {error && (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        </section>
      ) : null}

      {kind === "peptide" ? (
        peptideResult ? (
          <>
            <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-lg font-semibold text-slate-900">Peptide Annotation Ready</h3>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <SummaryCard label="Annotated Samples" value={String(peptideResult.rows)} />
                <SummaryCard label="Metadata Source" value="peptide file names" />
              </div>
            </section>
            <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-lg font-semibold text-slate-900">Metadata</h3>
              <div className="mt-4">
                <PreviewTable
                  rows={peptideResult.preview}
                  emptyText="No peptide metadata rows available."
                />
              </div>
            </section>
          </>
        ) : (
          <section className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
            No peptide annotation result yet.
          </section>
        )
      ) : result ? (
        <>
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">Result Summary</h3>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <SummaryCard label="Source Rows" value={String(result.sourceRows)} />
              <SummaryCard label="Metadata Rows" value={String(result.metadataRows)} />
              <SummaryCard label="Conditions" value={String(result.conditionCount)} />
              <SummaryCard label="Filtered Rows" value={String(result.filteredRows)} />
            </div>

            {visibleWarnings.length > 0 && (
              <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
                {visibleWarnings.join(" ")}
              </div>
            )}
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">Filtered Data</h3>
            <div className="mt-4">
              <PreviewTable
                rows={result.filteredPreview}
                emptyText="No filtered rows available."
                downloadAction={{
                  label:
                    downloadBusyKey === `${kind}:filtered`
                      ? "Downloading..."
                      : "Download Full CSV",
                  onClick: () => handleDownloadFullData(kind, "filtered"),
                  disabled: downloadBusyKey !== null,
                }}
              />
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-slate-900">Metadata</h3>
            <div className="mt-4">
              <PreviewTable
                rows={result.metadataPreview}
                emptyText="No metadata rows available."
                downloadAction={{
                  label:
                    downloadBusyKey === `${kind}:metadata`
                      ? "Downloading..."
                      : "Download Full CSV",
                  onClick: () => handleDownloadFullData(kind, "metadata"),
                  disabled: downloadBusyKey !== null,
                }}
              />
            </div>
          </section>

          {kind === "phospho" ? (
            <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="text-lg font-semibold text-slate-900">
                Aggregate to Phosphoprotein
              </h3>

              {canAggregatePhosprot ? (
                <>
                  <p className="mt-2 text-sm text-slate-600">
                    Aggregate the current uploaded and annotated phosphosite dataset to
                    phosphoprotein level.
                  </p>
                  <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end">
                    <div className="grid gap-3 lg:grid-cols-2">
                      <div>
                        <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="annotation-aggregation-mode">
                          Aggregation mode
                        </label>
                        <select id="annotation-aggregation-mode"
                          value={phosprotMode}
                          onChange={(e) =>
                            setPhosprotMode(e.target.value as PhosprotAggregationMode)
                          }
                          className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
                        >
                          <option value="robust_site_median">robust_site_median</option>
                          <option value="sum_propagate_na">sum_propagate_na</option>
                          <option value="sum_ignore_na">sum_ignore_na</option>
                          <option value="mean">mean</option>
                        </select>
                        <p className="mt-2 text-xs leading-5 text-slate-500">
                          {PHOSPROT_MODE_DESCRIPTIONS[phosprotMode]}
                        </p>
                      </div>
                      <div>
                        <label className="mb-2 block text-sm font-medium text-slate-700" htmlFor="annotation-source">
                          Source data
                        </label>
                        <select id="annotation-source"
                          value={phosprotSource}
                          onChange={(e) =>
                            setPhosprotSource(e.target.value as PhosprotAggregationSource)
                          }
                          className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
                        >
                          <option value="non_imputed">Non-imputed phospho</option>
                          {phosphoImputationAvailable ? (
                            <option value="imputed">Imputed phospho</option>
                          ) : null}
                        </select>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={handleAggregatePhosprot}
                      disabled={!currentDatasets?.phospho || phosprotBusy}
                      className="rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {phosprotBusy ? "Aggregating..." : "Aggregate to Phosphoprotein"}
                    </button>
                  </div>
                </>
              ) : (
                <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                  Generate phospho annotation first to enable aggregation.
                </div>
              )}

              <div className="mt-3 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600">
                {currentDatasets?.phosprot ? (
                  <>
                    Current phosphoprotein dataset: {currentDatasets.phosprot.filename} (
                    {currentDatasets.phosprot.rows} rows)
                  </>
                ) : (
                  "No phosphoprotein dataset loaded yet."
                )}
              </div>

              {phosprotResult ? (
                <div className="mt-3 space-y-3">
                  <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                    Phosphoprotein annotation ready: {phosprotResult.filteredRows} filtered rows,{" "}
                    {phosprotResult.conditionCount} conditions.
                  </div>
                  <PreviewTable
                    rows={phosprotResult.filteredPreview}
                    emptyText="No phosphoprotein filtered rows available."
                    downloadAction={{
                      label:
                        downloadBusyKey === "phosprot:source"
                          ? "Downloading..."
                          : "Download CSV",
                      onClick: () => handleDownloadFullData("phosprot", "source"),
                      disabled: downloadBusyKey !== null,
                    }}
                  />
                </div>
              ) : null}
            </section>
          ) : null}
        </>
      ) : (
        <section className="rounded-2xl border border-dashed border-slate-300 bg-white p-10 text-center text-slate-500">
          No annotation result yet.
        </section>
      )}
    </div>
  );
}
