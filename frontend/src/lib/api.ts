import type {
  ChatProvider,
  ChatMessage,
  CloudAiConsentStatus,
  AnnotationGenerateRequest,
  AnovaRequest,
  AnovaResultResponse,
  AnalysisVolcanoRequest,
  AnalysisVolcanoResponse,
  AnnotationKind,
  AnnotationResultResponse,
  Log2DetectionRequest,
  Log2DetectionResponse,
  ComparisonOptionsResponse,
  ComparisonTableResponse,
  CompletenessTablesResponse,
  ConditionPaletteResponse,
  DistributionSummaryResponse,
  CurrentDatasetsResponse,
  DatasetPackagesResponse,
  DatasetPreviewResponse,
  DatasetKind,
  EnrichmentRequest,
  EnrichmentResultResponse,
  ListEnrichmentRequest,
  ListEnrichmentResultResponse,
  IdTranslationRequest,
  IdTranslationResponse,
  ImputationResultResponse,
  ImputationRunRequest,
  MetadataUploadResponse,
  MetadataAnnotationKind,
  PairingUpdateRequest,
  PathwayOptionsResponse,
  PeptideCollapseRequest,
  PeptideCollapseResponse,
  PhosphoOptionsResponse,
  PhosphoTableResponse,
  PeptideCoverageResponse,
  PeptideMetadataResponse,
  PeptideMetadataGenerateRequest,
  PeptideOverviewResponse,
  PeptideQuantityOptionsResponse,
  PeptidePathResponse,
  PeptideSpecies,
  QcSummaryResponse,
  PhosprotAggregationMode,
  PhosprotAggregationSource,
  NormalizationCapabilityResponse,
  RRuntimeStatusResponse,
  SingleProteinOptionsResponse,
  SingleProteinTableResponse,
  QcPcaFeatureSummary,
  QcPlotOptionsResponse,
  QcTableResponse,
  RestoreImportResponse,
  SimulationRequest,
  SimulationResultResponse,
  StatisticalOptionsResponse,
  SummaryReportRequest,
  SummaryReportResponse,
  ViewerAuthLoginResponse,
  ViewerAuthStatusResponse,
  ToolAuthLoginResponse,
  ToolAuthStatusResponse,
  OllamaGpuStatusResponse,
  ModelCapabilityResponse,
  OllamaModelManageResponse,
  OllamaModelsResponse,
  SummaryTablesResponse,
  VisualizationDataSource,
  VolcanoControlRequest,
  VolcanoResultResponse,
  VolcanoRequest,
} from "./types";
import { getActiveAdvancedPlotSettingsJson } from "./appSettings";
import { syncSummaryReportStateWithDatasets } from "./reportState";
import { emitDatasetStateChanged } from "./datasetEvents";
import { normalizePlotSizeParams } from "./plotLimits";
import { isAnalysisMutation, unsavedAnalysis } from "./unsavedAnalysis";
import { TAB_API_PREFIX } from "./tabSession";

// Local wrapper only (not a global fetch replacement). A failed/aborted write
// remains conservatively dirty because the server may already have committed it.
let pendingUiRequests = 0;
export function hasPendingUiRequests() { return pendingUiRequests > 0; }

async function fetch(input: string, init?: RequestInit): Promise<Response> {
  const tracked = !input.includes("/api/chat/");
  if (tracked) pendingUiRequests++;
  const finish = isAnalysisMutation(input, init?.method) ? unsavedAnalysis.beginMutation() : null;
  try {
    return await globalThis.fetch(input, init);
  } finally {
    finish?.();
    if (tracked) pendingUiRequests--;
  }
}

const API_BASE = `${import.meta.env.VITE_API_BASE_URL ?? ""}${TAB_API_PREFIX}`;

export type AssistantView = {
  module: string; workflow: string; mode: string;
  advancedOptions?: boolean;
  controls: import("./assistantControls").AssistantControl[];
  destinations: Record<string, string>;
};

export type AssistantResult = {
  usedEvidenceFallback?: boolean;
  explainAfterChanges?: boolean;
  needsClarification?: boolean;
  model: string; answer: string; revision: number;
  actions: import("./assistantControls").AssistantAction[];
  evidence: { tool: string; status: string; text: string }[];
};

export async function assistantStep(
  payload: { message: string; messages?: ChatMessage[]; provider?: ChatProvider; model?: string; gpuEnabled?: boolean; apiKey?: string; ollamaUrl?: string; view: AssistantView; receipts: string[]; answerOnly?: boolean; conversationState?: import("./assistantConversation").ConversationState | null },
  signal: AbortSignal,
): Promise<AssistantResult> {
  const response = await fetch(`${API_BASE}/api/chat/assistant`, {
    method: "POST", headers: { "Content-Type": "application/json" }, signal, body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (response.status === 428 && data.detail?.code === "cloud_ai_consent_required") {
    throw new CloudAiConsentRequiredError(normalizeCloudAiConsentStatus(data.detail));
  }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The assistant could not complete this step.");
  return data;
}
let DATASET_SCOPE_NONCE = 0;

export type ApiRequestOptions = {
  signal?: AbortSignal;
};

export class CloudAiConsentRequiredError extends Error {
  status: CloudAiConsentStatus;

  constructor(status: CloudAiConsentStatus) {
    super(`Cloud AI consent is required for ${status.providerLabel}.`);
    this.name = "CloudAiConsentRequiredError";
    this.status = status;
  }
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException
    ? error.name === "AbortError"
    : error instanceof Error && error.name === "AbortError";
}

function bumpDatasetScopeNonce() {
  DATASET_SCOPE_NONCE += 1;
}

async function parseJson(response: Response) {
  const text = await response.text();
  if (!text) return null;

  try {
    return JSON.parse(text);
  } catch {
    throw new Error("Backend returned invalid JSON");
  }
}

export async function getViewerAuthStatus(): Promise<ViewerAuthStatusResponse> {
  const response = await fetch(`${API_BASE}/api/viewer/auth/status`);
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load viewer auth status"
    );
  }
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    enabled: Boolean(raw.enabled),
    authenticated: Boolean(raw.authenticated),
    project: raw.project == null ? null : String(raw.project),
    projectLabel: raw.projectLabel == null ? null : String(raw.projectLabel),
  };
}

export async function loginViewer(password: string): Promise<ViewerAuthLoginResponse> {
  const response = await fetch(`${API_BASE}/api/viewer/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ password }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Viewer login failed"
    );
  }
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    ok: Boolean(raw.ok),
    project: String(raw.project ?? ""),
    projectLabel: String(raw.projectLabel ?? raw.project ?? ""),
  };
}

export async function getRRuntimeStatus(refresh = false): Promise<RRuntimeStatusResponse> {
  const suffix = refresh ? "?refresh=1" : "";
  const response = await fetch(`${API_BASE}/api/runtime/r${suffix}`, {
    cache: refresh ? "no-store" : "default",
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to detect R runtime"
    );
  }
  return data as RRuntimeStatusResponse;
}

export async function getNormalizationCapability(
  refresh = false
): Promise<NormalizationCapabilityResponse> {
  const suffix = refresh ? "?refresh=1" : "";
  const response = await fetch(`${API_BASE}/api/runtime/normalization${suffix}`, {
    cache: refresh ? "no-store" : "default",
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to detect normalization capabilities"
    );
  }
  const payload = data as Partial<NormalizationCapabilityResponse>;
  return {
    methods: Array.isArray(payload.methods)
      ? (payload.methods as NormalizationCapabilityResponse["methods"])
      : ["none", "median", "quantile"],
    vsnAvailable: Boolean(payload.vsnAvailable),
    vsnUnavailableReason: payload.vsnUnavailableReason ?? null,
    vsnPackageVersion: payload.vsnPackageVersion ?? null,
  };
}

export async function loginViewerQr(token: string): Promise<ViewerAuthLoginResponse> {
  const response = await fetch(`${API_BASE}/api/viewer/auth/qr-login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ token }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Viewer QR login failed"
    );
  }
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    ok: Boolean(raw.ok),
    project: String(raw.project ?? ""),
    projectLabel: String(raw.projectLabel ?? raw.project ?? ""),
  };
}

export async function logoutViewer(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/viewer/auth/logout`, {
    method: "POST",
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Viewer logout failed"
    );
  }
}

export async function getToolAuthStatus(): Promise<ToolAuthStatusResponse> {
  const response = await fetch(`${API_BASE}/api/tool/auth/status`);
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load tool auth status"
    );
  }
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    enabled: Boolean(raw.enabled),
    authenticated: Boolean(raw.authenticated),
  };
}

export async function loginTool(password: string): Promise<ToolAuthLoginResponse> {
  const response = await fetch(`${API_BASE}/api/tool/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ password }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Tool login failed"
    );
  }
  return { ok: Boolean((data as Record<string, unknown> | null)?.ok) };
}

export async function loginToolLink(token: string): Promise<ToolAuthLoginResponse> {
  const response = await fetch(`${API_BASE}/api/tool/auth/link-login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ token }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Tool access link failed"
    );
  }
  return { ok: Boolean((data as Record<string, unknown> | null)?.ok) };
}

export async function logoutTool(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/tool/auth/logout`, {
    method: "POST",
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Tool logout failed"
    );
  }
}

export async function uploadDataset(
  file: File,
  kind: Extract<DatasetKind, "protein" | "phospho" | "phosprot">,
  packageName?: string,
  sourcePath?: string
): Promise<DatasetPreviewResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  if (packageName && packageName.trim()) {
    form.append("packageName", packageName.trim());
  }
  if (sourcePath && sourcePath.trim()) {
    form.append("sourcePath", sourcePath.trim());
  }

  const response = await fetch(`${API_BASE}/api/datasets/upload`, {
    method: "POST",
    body: form,
  });

  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Upload failed"
    );
  }

  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
  return data as DatasetPreviewResponse;
}

export async function saveTableDatasetPath(
  path: string,
  kind: Extract<DatasetKind, "protein" | "phospho" | "phosprot">,
  packageName?: string
): Promise<DatasetPreviewResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/table-path`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      path,
      kind,
      packageName: packageName?.trim() || null,
    }),
  });

  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Saving dataset path failed"
    );
  }

  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
  return data as DatasetPreviewResponse;
}

function resolveDownloadFilename(response: Response, fallback: string): string {
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  if (!match || !match[1]) return fallback;
  return match[1].trim() || fallback;
}

export async function downloadRestoreState(
  uiState: Record<string, unknown>,
  options: { portable?: boolean } = {}
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE}/api/restore/export`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ uiState, portable: options.portable ?? false }),
  });
  if (!response.ok) {
    const data = await parseJson(response);
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to export restore state"
    );
  }
  const blob = await response.blob();
  const filename = resolveDownloadFilename(response, "copylot_state.copylotstate");
  return { blob, filename };
}

export async function importRestoreState(
  stateFile: File,
  replacements: Array<{
    packageName: string;
    kind: "protein" | "phospho" | "phosprot" | "peptide";
    file: File;
    sourcePath?: string | null;
  }> = []
): Promise<RestoreImportResponse> {
  const form = new FormData();
  form.append("stateFile", stateFile);
  if (replacements.length > 0) {
    const manifest = replacements.map((item) => ({
      packageName: item.packageName,
      kind: item.kind,
      sourcePath: item.sourcePath?.trim() || null,
    }));
    form.append("replacementsManifest", JSON.stringify(manifest));
    for (const item of replacements) {
      form.append("replacements", item.file);
    }
  }

  const response = await fetch(`${API_BASE}/api/restore/import`, {
    method: "POST",
    body: form,
  });
  const data = await parseJson(response);

  if (response.status === 409) {
    return (data ?? {
      ok: false,
      uiState: {},
      warnings: [],
      missingFiles: [],
      restoredDatasets: [],
      restoredAnnotations: [],
    }) as RestoreImportResponse;
  }

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to import restore state"
    );
  }

  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
  return data as RestoreImportResponse;
}

export async function resetBrowserSessionState(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/restore/browser-session-reset`, {
    method: "POST",
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to reset browser session state"
    );
  }
}

export async function savePeptidePath(path: string, packageName?: string): Promise<PeptidePathResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/peptide-path`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      path,
      packageName: packageName?.trim() || null,
    }),
  });

  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Saving peptide path failed"
    );
  }

  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
  return data as PeptidePathResponse;
}

export async function uploadPeptideFile(file: File, packageName?: string): Promise<PeptidePathResponse> {
  const form = new FormData();
  form.append("file", file);
  if (packageName && packageName.trim()) {
    form.append("packageName", packageName.trim());
  }

  const response = await fetch(`${API_BASE}/api/datasets/peptide-file`, {
    method: "POST",
    body: form,
  });

  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Saving peptide file failed"
    );
  }

  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
  return data as PeptidePathResponse;
}

export async function getCurrentDatasets(
  requestOptions: ApiRequestOptions = {}
): Promise<CurrentDatasetsResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/current`, { signal: requestOptions.signal });
  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load current datasets"
    );
  }

  const payloadRaw = data as CurrentDatasetsResponse;
  const payload: CurrentDatasetsResponse = {
    activePackage: payloadRaw.activePackage || "Data",
    availablePackages: Array.isArray(payloadRaw.availablePackages) ? payloadRaw.availablePackages : ["Data"],
    activeMetadataProfile: payloadRaw.activeMetadataProfile || "Metadata",
    availableMetadataProfiles: Array.isArray(payloadRaw.availableMetadataProfiles)
      ? payloadRaw.availableMetadataProfiles
      : [payloadRaw.activeMetadataProfile || "Metadata"],
    autoGeneratedMetadataProfiles: Array.isArray(payloadRaw.autoGeneratedMetadataProfiles)
      ? payloadRaw.autoGeneratedMetadataProfiles
      : [],
    protein: payloadRaw.protein ?? null,
    phospho: payloadRaw.phospho ?? null,
    phosprot: payloadRaw.phosprot ?? null,
    peptide: payloadRaw.peptide ?? null,
  };
  syncSummaryReportStateWithDatasets(payload);
  return payload;
}

export async function getDatasetPackages(): Promise<DatasetPackagesResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/packages`);
  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load dataset packages"
    );
  }

  return data as DatasetPackagesResponse;
}

export async function createDatasetPackage(packageName: string): Promise<CurrentDatasetsResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/packages/create`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ packageName }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to create dataset package"
    );
  }
  const payload = data as CurrentDatasetsResponse;
  syncSummaryReportStateWithDatasets(payload);
  bumpDatasetScopeNonce();
  emitDatasetStateChanged(payload);
  return payload;
}

export async function renameDatasetPackage(
  oldName: string,
  newName: string
): Promise<CurrentDatasetsResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/packages/rename`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ oldName, newName }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to rename dataset package"
    );
  }
  const payload = data as CurrentDatasetsResponse;
  syncSummaryReportStateWithDatasets(payload);
  bumpDatasetScopeNonce();
  emitDatasetStateChanged(payload);
  return payload;
}

export async function setActiveDatasetPackage(packageName: string): Promise<CurrentDatasetsResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/active`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ packageName }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to switch dataset package"
    );
  }

  const payload = data as CurrentDatasetsResponse;
  syncSummaryReportStateWithDatasets(payload);
  bumpDatasetScopeNonce();
  emitDatasetStateChanged(payload);
  return payload;
}

export async function createMetadataProfile(
  profileName: string
): Promise<CurrentDatasetsResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/metadata/profiles/create`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ profileName }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to create metadata profile"
    );
  }
  const payload = data as CurrentDatasetsResponse;
  syncSummaryReportStateWithDatasets(payload);
  bumpDatasetScopeNonce();
  emitDatasetStateChanged(payload);
  return payload;
}

export async function deleteMetadataProfile(
  profileName: string
): Promise<CurrentDatasetsResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/metadata/profiles/delete`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ profileName }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to delete metadata profile"
    );
  }
  const payload = data as CurrentDatasetsResponse;
  syncSummaryReportStateWithDatasets(payload);
  bumpDatasetScopeNonce();
  emitDatasetStateChanged(payload);
  return payload;
}

export async function renameMetadataProfile(
  oldName: string,
  newName: string
): Promise<CurrentDatasetsResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/metadata/profiles/rename`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ oldName, newName }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to rename metadata profile"
    );
  }
  const payload = data as CurrentDatasetsResponse;
  syncSummaryReportStateWithDatasets(payload);
  bumpDatasetScopeNonce();
  emitDatasetStateChanged(payload);
  return payload;
}

export async function setActiveMetadataProfile(
  profileName: string
): Promise<CurrentDatasetsResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/metadata/profiles/active`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ profileName }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to switch metadata profile"
    );
  }
  const payload = data as CurrentDatasetsResponse;
  syncSummaryReportStateWithDatasets(payload);
  bumpDatasetScopeNonce();
  emitDatasetStateChanged(payload);
  return payload;
}

export async function getPeptideOverview(
  requestOptions: ApiRequestOptions = {}
): Promise<PeptideOverviewResponse> {
  const response = await fetch(`${API_BASE}/api/peptide/overview`, { signal: requestOptions.signal });
  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load peptide overview"
    );
  }

  return data as PeptideOverviewResponse;
}

export async function uploadPeptideMetadata(file: File): Promise<PeptideMetadataResponse> {
  const form = new FormData();
  form.append("file", file);

  const response = await fetch(`${API_BASE}/api/peptide/metadata/upload`, {
    method: "POST",
    body: form,
  });

  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to upload peptide metadata"
    );
  }

  return data as PeptideMetadataResponse;
}

export async function getCurrentPeptideMetadata(): Promise<PeptideMetadataResponse | null> {
  const response = await fetch(`${API_BASE}/api/peptide/metadata/current`);
  const data = await parseJson(response);

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load peptide metadata"
    );
  }

  return data as PeptideMetadataResponse;
}

export async function clearCurrentPeptideMetadata(): Promise<void> {
  const response = await fetch(`${API_BASE}/api/peptide/metadata/current`, {
    method: "DELETE",
  });
  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to clear peptide metadata"
    );
  }
}

export async function getPeptideSequenceCoverage(
  species: PeptideSpecies,
  protein: string,
  chunkSize: number,
  requestOptions: ApiRequestOptions = {}
): Promise<PeptideCoverageResponse> {
  const response = await fetch(
    buildPlotUrl("/api/peptide/sequence-coverage", { species, protein, chunkSize }),
    { signal: requestOptions.signal }
  );
  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to calculate peptide sequence coverage"
    );
  }

  return data as PeptideCoverageResponse;
}

export async function generateAnnotation(
  payload: AnnotationGenerateRequest
): Promise<AnnotationResultResponse> {
  const response = await fetch(`${API_BASE}/api/annotations/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to generate annotation"
    );
  }

  return data as AnnotationResultResponse;
}

export async function generatePeptideMetadata(
  payload: PeptideMetadataGenerateRequest
): Promise<PeptideMetadataResponse> {
  const response = await fetch(`${API_BASE}/api/peptide/metadata/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to generate peptide metadata"
    );
  }

  return data as PeptideMetadataResponse;
}

export async function detectAnnotationLog2Scale(
  payload: Log2DetectionRequest
): Promise<Log2DetectionResponse> {
  const response = await fetch(`${API_BASE}/api/annotations/log2-detect`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to detect intensity scale"
    );
  }
  return data as Log2DetectionResponse;
}

export async function getCurrentAnnotation(
  kind: AnnotationKind,
  requestOptions: ApiRequestOptions = {}
): Promise<AnnotationResultResponse> {
  const response = await fetch(`${API_BASE}/api/annotations/current/${kind}`, {
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to fetch current annotation"
    );
  }

  return data as AnnotationResultResponse;
}

export async function downloadCurrentAnnotationFilteredData(
  kind: AnnotationKind
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE}/api/annotations/current/${kind}/filtered/download`);
  if (!response.ok) {
    const data = await parseJson(response);
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to download filtered annotation data"
    );
  }
  const blob = await response.blob();
  const filename = resolveDownloadFilename(response, `${kind}_filtered_data_full.csv`);
  return { blob, filename };
}

export async function downloadCurrentAnnotationSourceData(
  kind: AnnotationKind
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE}/api/annotations/current/${kind}/source/download`);
  if (!response.ok) {
    const data = await parseJson(response);
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to download non-filtered annotation data"
    );
  }
  const blob = await response.blob();
  const filename = resolveDownloadFilename(response, `${kind}_data_full.csv`);
  return { blob, filename };
}

export async function downloadCurrentAnnotationMetadataData(
  kind: AnnotationKind
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE}/api/annotations/current/${kind}/metadata/download`);
  if (!response.ok) {
    const data = await parseJson(response);
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to download metadata annotation data"
    );
  }
  const blob = await response.blob();
  const filename = resolveDownloadFilename(response, `${kind}_metadata_full.csv`);
  return { blob, filename };
}

export async function updateAnnotationPairing(
  payload: PairingUpdateRequest
): Promise<AnnotationResultResponse> {
  const response = await fetch(`${API_BASE}/api/annotations/pairing`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to save sample pairing"
    );
  }
  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
  return data as AnnotationResultResponse;
}

export function pairingIsReady(
  condition1: string,
  condition2: string,
  samplesByCondition: Record<string, string[]>,
  pairIdsBySample: Record<string, string>
) {
  if (!condition1 || !condition2 || condition1 === condition2) return false;
  const leftSamples = samplesByCondition[condition1] ?? [];
  const rightSamples = samplesByCondition[condition2] ?? [];
  const leftIds = leftSamples.map((sample) => pairIdsBySample[sample] ?? "").filter(Boolean);
  const rightIds = rightSamples.map((sample) => pairIdsBySample[sample] ?? "").filter(Boolean);
  if (new Set(leftIds).size !== leftIds.length || new Set(rightIds).size !== rightIds.length) {
    return false;
  }
  const rightIdSet = new Set(rightIds);
  return leftIds.filter((pairId) => rightIdSet.has(pairId)).length >= 2;
}

export async function uploadAnnotationMetadata(
  file: File,
  kind: MetadataAnnotationKind
): Promise<MetadataUploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);

  const response = await fetch(`${API_BASE}/api/annotations/metadata/upload`, {
    method: "POST",
    body: form,
  });

  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to upload metadata"
    );
  }

  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
  return data as MetadataUploadResponse;
}

export async function getUploadedAnnotationMetadata(
  kind: MetadataAnnotationKind
): Promise<MetadataUploadResponse | null> {
  const response = await fetch(`${API_BASE}/api/annotations/metadata/current/${kind}`);
  const data = await parseJson(response);

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load uploaded metadata"
    );
  }

  return data as MetadataUploadResponse;
}

export async function clearUploadedAnnotationMetadata(
  kind: MetadataAnnotationKind
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/annotations/metadata/current/${kind}`, {
    method: "DELETE",
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to clear uploaded metadata"
    );
  }
  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
}

export async function runImputation(
  payload: ImputationRunRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<ImputationResultResponse> {
  const response = await fetch(`${API_BASE}/api/data-tools/imputation/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to run imputation"
    );
  }
  return data as ImputationResultResponse;
}

export async function downloadImputationCsv(
  payload: ImputationRunRequest
): Promise<Blob> {
  const response = await fetch(`${API_BASE}/api/data-tools/imputation/download`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const data = await parseJson(response);
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to download imputed CSV"
    );
  }

  return response.blob();
}

export async function getDistributionSummary(
  kind: AnnotationKind,
  requestOptions: ApiRequestOptions = {}
): Promise<DistributionSummaryResponse> {
  const response = await fetch(`${API_BASE}/api/data-tools/distribution/${kind}`, {
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load distribution summary"
    );
  }
  return data as DistributionSummaryResponse;
}

export async function runIdTranslation(
  payload: IdTranslationRequest
): Promise<IdTranslationResponse> {
  const response = await fetch(`${API_BASE}/api/data-tools/id-translation/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to translate IDs"
    );
  }
  return data as IdTranslationResponse;
}

export async function downloadIdTranslation(
  payload: IdTranslationRequest
): Promise<Blob> {
  const response = await fetch(`${API_BASE}/api/data-tools/id-translation/download`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const data = await parseJson(response);
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to download translated table"
    );
  }

  return response.blob();
}

export async function aggregatePhosprot(
  mode: PhosprotAggregationMode,
  source: PhosprotAggregationSource
): Promise<AnnotationResultResponse> {
  const response = await fetch(`${API_BASE}/api/annotations/phosprot/aggregate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ mode, source }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to aggregate phosphoprotein dataset"
    );
  }
  return data as AnnotationResultResponse;
}

export async function uploadPhosprot(
  file: File,
  isLog2Transformed?: boolean
): Promise<AnnotationResultResponse> {
  const form = new FormData();
  form.append("file", file);
  if (typeof isLog2Transformed === "boolean") {
    form.append("isLog2Transformed", String(isLog2Transformed));
  }

  const response = await fetch(`${API_BASE}/api/annotations/phosprot/upload`, {
    method: "POST",
    body: form,
  });

  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to upload phosphoprotein dataset"
    );
  }
  return data as AnnotationResultResponse;
}

export async function getConditionPalette(
  kind: AnnotationKind,
  requestOptions: ApiRequestOptions = {}
): Promise<ConditionPaletteResponse> {
  const response = await fetch(`${API_BASE}/api/data-tools/condition-colors/${kind}`, {
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load condition colors"
    );
  }
  return data as ConditionPaletteResponse;
}

export async function setConditionPalette(
  kind: AnnotationKind,
  palette: Record<string, string>
): Promise<ConditionPaletteResponse> {
  const response = await fetch(`${API_BASE}/api/data-tools/condition-colors/${kind}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ palette }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to save condition colors"
    );
  }
  return data as ConditionPaletteResponse;
}

export async function getCompletenessTables(
  kind: AnnotationKind,
  params?: Record<string, string | number | boolean>,
  requestOptions: ApiRequestOptions = {}
): Promise<CompletenessTablesResponse> {
  const response = await fetch(buildPlotUrl(`/api/data-tools/completeness/${kind}/tables`, params), {
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load completeness tables"
    );
  }
  return data as CompletenessTablesResponse;
}

export async function getQcSummary(kind: AnnotationKind): Promise<QcSummaryResponse> {
  const response = await fetch(`${API_BASE}/api/qc/summary/${kind}`);
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load QC summary"
    );
  }
  return data as QcSummaryResponse;
}

export async function getQcPlotOptions(
  kind: AnnotationKind,
  requestOptions: ApiRequestOptions = {}
): Promise<QcPlotOptionsResponse> {
  const response = await fetch(`${API_BASE}/api/plots/qc/${kind}/options`, {
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load QC plot options"
    );
  }
  const payload = data as Partial<QcPlotOptionsResponse>;
  return {
    conditions: Array.isArray(payload.conditions) ? payload.conditions : [],
    imputedAvailable: Boolean(payload.imputedAvailable),
    samples: Array.isArray(payload.samples) ? payload.samples : [],
    sampleLabels: payload.sampleLabels ?? {},
    sampleLabelsWithId: payload.sampleLabelsWithId ?? {},
  };
}

export async function getPeptideQuantityOptions(
  requestOptions: ApiRequestOptions = {}
): Promise<PeptideQuantityOptionsResponse> {
  const response = await fetch(`${API_BASE}/api/peptide/quantity-options`, {
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load peptide abundance columns"
    );
  }
  const payload = data as Partial<PeptideQuantityOptionsResponse>;
  return {
    columns: Array.isArray(payload.columns) ? payload.columns : [],
    defaultColumn: typeof payload.defaultColumn === "string" ? payload.defaultColumn : null,
    requiresSelection: Boolean(payload.requiresSelection),
  };
}

export async function getQcPcaFeatures(
  kind: AnnotationKind,
  dataSource: string,
  plotDim: string,
  requestOptions: ApiRequestOptions = {}
): Promise<QcPcaFeatureSummary> {
  const query = new URLSearchParams({ dataSource, plotDim });
  const response = await fetch(`${API_BASE}/api/plots/qc/${kind}/pca-features?${query.toString()}`, {
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load PCA feature summary"
    );
  }
  const payload = data as Partial<QcPcaFeatureSummary>;
  return {
    featuresTotal: Number(payload.featuresTotal ?? 0),
    featuresComplete: Number(payload.featuresComplete ?? 0),
    featuresUsed: Number(payload.featuresUsed ?? 0),
    featuresRequired: Number(payload.featuresRequired ?? 2),
  };
}

export async function getQcTable(
  kind: AnnotationKind,
  tab: "coverage" | "boxplot" | "cv",
  params?: Record<string, string | number | boolean>,
  requestOptions: ApiRequestOptions = {}
): Promise<QcTableResponse> {
  let path = `/api/plots/qc/${kind}/${tab}-table`;
  if (tab === "coverage") path = `/api/plots/qc/${kind}/coverage-table`;
  if (tab === "boxplot") path = `/api/plots/qc/${kind}/boxplot-table`;
  if (tab === "cv") path = `/api/plots/qc/${kind}/cv-table`;

  const response = await fetch(buildPlotUrl(path, params), { signal: requestOptions.signal });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load QC table"
    );
  }
  return data as QcTableResponse;
}

export async function getStatisticalOptions(
  kind: AnnotationKind,
  requestOptions: ApiRequestOptions = {}
): Promise<StatisticalOptionsResponse> {
  const response = await fetch(`${API_BASE}/api/stats/options/${kind}`, {
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load statistical options"
    );
  }
  const payloadRaw = data as Partial<StatisticalOptionsResponse>;
  return {
    kind: (payloadRaw.kind as AnnotationKind) ?? kind,
    sourceUsed: payloadRaw.sourceUsed ?? "raw",
    imputedAvailable: Boolean(payloadRaw.imputedAvailable),
    availableConditions: Array.isArray(payloadRaw.availableConditions)
      ? payloadRaw.availableConditions
      : [],
    samplesByCondition:
      payloadRaw.samplesByCondition && typeof payloadRaw.samplesByCondition === "object"
        ? payloadRaw.samplesByCondition
        : {},
    pairIdsBySample:
      payloadRaw.pairIdsBySample && typeof payloadRaw.pairIdsBySample === "object"
        ? payloadRaw.pairIdsBySample
        : {},
    availableIdentifiers: Array.isArray(payloadRaw.availableIdentifiers)
      ? payloadRaw.availableIdentifiers
      : [],
    warnings: Array.isArray(payloadRaw.warnings) ? payloadRaw.warnings : [],
  };
}

export async function runVolcanoAnalysis(
  payload: VolcanoRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<VolcanoResultResponse> {
  const response = await fetch(`${API_BASE}/api/stats/volcano/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to run volcano analysis"
    );
  }
  return data as VolcanoResultResponse;
}

export async function runVolcanoControlAnalysis(
  payload: VolcanoControlRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<VolcanoResultResponse> {
  const response = await fetch(`${API_BASE}/api/stats/volcano-control/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to run control volcano analysis"
    );
  }
  return data as VolcanoResultResponse;
}

export async function runAnovaAnalysis(
  payload: AnovaRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<AnovaResultResponse> {
  const response = await fetch(`${API_BASE}/api/stats/anova/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to run ANOVA analysis"
    );
  }
  return data as AnovaResultResponse;
}

export async function runEnrichmentAnalysis(
  payload: EnrichmentRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<EnrichmentResultResponse> {
  const response = await fetch(`${API_BASE}/api/stats/ora/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to run enrichment analysis"
    );
  }
  return data as EnrichmentResultResponse;
}

export async function runListEnrichmentAnalysis(
  payload: ListEnrichmentRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<ListEnrichmentResultResponse> {
  const response = await fetch(`${API_BASE}/api/stats/ora/list/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to run list enrichment analysis"
    );
  }
  return data as ListEnrichmentResultResponse;
}

export async function runAnalysisVolcanoData(
  payload: AnalysisVolcanoRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<AnalysisVolcanoResponse> {
  const response = await fetch(`${API_BASE}/api/analysis/volcano/data`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load analysis volcano data"
    );
  }
  return data as AnalysisVolcanoResponse;
}

function normalizeCloudAiConsentStatus(value: unknown): CloudAiConsentStatus {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const provider: ChatProvider =
    raw.provider === "openai" || raw.provider === "anthropic" || raw.provider === "gemini"
      ? raw.provider
      : "ollama";
  return {
    provider,
    providerLabel: String(raw.providerLabel ?? provider),
    required: Boolean(raw.required),
    granted: Boolean(raw.granted),
    disclosureVersion: String(raw.disclosureVersion ?? ""),
    transmitted: Array.isArray(raw.transmitted) ? raw.transmitted.map(String) : [],
    excluded: Array.isArray(raw.excluded) ? raw.excluded.map(String) : [],
    notice: String(raw.notice ?? ""),
  };
}

export async function getCloudAiConsentStatus(provider: ChatProvider): Promise<CloudAiConsentStatus> {
  const response = await fetch(`${API_BASE}/api/chat/cloud-consent/${encodeURIComponent(provider)}`);
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load cloud AI consent status"
    );
  }
  return normalizeCloudAiConsentStatus(data);
}

export async function grantCloudAiConsent(
  provider: ChatProvider,
  disclosureVersion: string
): Promise<CloudAiConsentStatus> {
  const response = await fetch(
    `${API_BASE}/api/chat/cloud-consent/${encodeURIComponent(provider)}/grant`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ disclosureVersion }),
    }
  );
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to confirm cloud AI consent"
    );
  }
  return normalizeCloudAiConsentStatus(data);
}

export async function revokeCloudAiConsent(provider: ChatProvider): Promise<CloudAiConsentStatus> {
  const response = await fetch(
    `${API_BASE}/api/chat/cloud-consent/${encodeURIComponent(provider)}/revoke`,
    { method: "POST" }
  );
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to revoke cloud AI consent"
    );
  }
  return normalizeCloudAiConsentStatus(data);
}

export async function getOllamaGpuStatus(endpoint?: string): Promise<OllamaGpuStatusResponse> {
  const url = endpoint?.trim()
    ? `${API_BASE}/api/chat/gpu-status?endpoint=${encodeURIComponent(endpoint.trim())}`
    : `${API_BASE}/api/chat/gpu-status`;
  const response = await fetch(url);
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load Ollama GPU status"
    );
  }
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    gpuEligible: Boolean(raw.gpuEligible),
    gpuEnabledDefault: Boolean(raw.gpuEnabledDefault),
    provider: raw.provider == null ? null : String(raw.provider),
    deviceName: raw.deviceName == null ? null : String(raw.deviceName),
    reason: raw.reason == null ? null : String(raw.reason),
    remoteEndpoint: Boolean(raw.remoteEndpoint),
    acceleration:
      String(raw.acceleration ?? "").toLowerCase() === "gpu"
        ? "gpu"
        : String(raw.acceleration ?? "").toLowerCase() === "cpu"
          ? "cpu"
          : "unknown",
  };
}

export async function getOllamaModels(endpoint?: string): Promise<OllamaModelsResponse> {
  const url = endpoint?.trim()
    ? `${API_BASE}/api/chat/models?endpoint=${encodeURIComponent(endpoint.trim())}`
    : `${API_BASE}/api/chat/models`;
  const response = await fetch(url);
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load Ollama models"
    );
  }
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    models: Array.isArray(raw.models) ? raw.models.map((item) => String(item)) : [],
    selectedModel: raw.selectedModel == null ? null : String(raw.selectedModel),
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map((item) => String(item)) : [],
  };
}

export async function installOllamaModel(model: string, endpoint?: string): Promise<OllamaModelManageResponse> {
  const response = await fetch(`${API_BASE}/api/chat/models/install`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ model, endpoint: endpoint?.trim() || null }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to install Ollama model"
    );
  }
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    ok: Boolean(raw.ok),
    action: String(raw.action) === "remove" ? "remove" : "install",
    model: String(raw.model ?? model),
    detail: String(raw.detail ?? ""),
    models: Array.isArray(raw.models) ? raw.models.map((item) => String(item)) : [],
    selectedModel: raw.selectedModel == null ? null : String(raw.selectedModel),
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map((item) => String(item)) : [],
  };
}

export async function removeOllamaModel(model: string, endpoint?: string): Promise<OllamaModelManageResponse> {
  const response = await fetch(`${API_BASE}/api/chat/models/remove`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ model, endpoint: endpoint?.trim() || null }),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to remove Ollama model"
    );
  }
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    ok: Boolean(raw.ok),
    action: "remove",
    model: String(raw.model ?? model),
    detail: String(raw.detail ?? ""),
    models: Array.isArray(raw.models) ? raw.models.map((item) => String(item)) : [],
    selectedModel: raw.selectedModel == null ? null : String(raw.selectedModel),
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map((item) => String(item)) : [],
  };
}

export async function getPathwayOptions(
  requestOptions: ApiRequestOptions = {}
): Promise<PathwayOptionsResponse> {
  const response = await fetch(`${API_BASE}/api/stats/pathways`, {
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load pathway options"
    );
  }
  return data as PathwayOptionsResponse;
}

export async function runSimulationAnalysis(
  payload: SimulationRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<SimulationResultResponse> {
  const response = await fetch(`${API_BASE}/api/stats/simulation/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to run simulation"
    );
  }
  return data as SimulationResultResponse;
}

export async function getSingleProteinOptions(
  kind: AnnotationKind,
  tab: "boxplot" | "lineplot" | "heatmap",
  identifier: "workflow" | "genes" = "workflow",
  dataSource: VisualizationDataSource = "log2",
  requestOptions: ApiRequestOptions = {}
): Promise<SingleProteinOptionsResponse> {
  const response = await fetch(
    buildPlotUrl(`/api/plots/single-protein/${kind}/options`, { tab, identifier, dataSource }),
    { signal: requestOptions.signal }
  );
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load single-protein options"
    );
  }
  return data as SingleProteinOptionsResponse;
}

export async function getSingleProteinTable(
  kind: AnnotationKind,
  tab: "boxplot" | "lineplot" | "heatmap",
  params?: Record<string, string | number | boolean>,
  requestOptions: ApiRequestOptions = {}
): Promise<SingleProteinTableResponse> {
  const response = await fetch(
    buildPlotUrl(`/api/plots/single-protein/${kind}/${tab}-table`, params),
    { signal: requestOptions.signal }
  );
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load single-protein table"
    );
  }
  return data as SingleProteinTableResponse;
}

export async function getPhosphoOptions(
  requestOptions: ApiRequestOptions = {}
): Promise<PhosphoOptionsResponse> {
  const response = await fetch(`${API_BASE}/api/plots/phospho/options`, {
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load phospho options"
    );
  }
  const payloadRaw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    ...payloadRaw,
    conditions: Array.isArray(payloadRaw.conditions)
      ? payloadRaw.conditions.map((value) => String(value))
      : [],
    samplesByCondition:
      payloadRaw.samplesByCondition && typeof payloadRaw.samplesByCondition === "object"
        ? payloadRaw.samplesByCondition
        : {},
    pairIdsBySample:
      payloadRaw.pairIdsBySample && typeof payloadRaw.pairIdsBySample === "object"
        ? payloadRaw.pairIdsBySample
        : {},
    features: Array.isArray(payloadRaw.features)
      ? payloadRaw.features.map((value) => String(value))
      : [],
    imputedAvailable: Boolean(payloadRaw.imputedAvailable),
  } as PhosphoOptionsResponse;
}

export async function getPhosphoTable(
  tab: "phosphositePlot" | "coverage" | "ksea" | "distribution" | "sty" | "phosprotRegulation",
  params?: Record<string, string | number | boolean>,
  requestOptions: ApiRequestOptions = {}
): Promise<PhosphoTableResponse> {
  let path = "/api/plots/phospho/phosphosite-plot-table";
  if (tab === "coverage") path = "/api/plots/phospho/coverage-table";
  if (tab === "ksea") path = "/api/plots/phospho/ksea-table";
  if (tab === "distribution") path = "/api/plots/phospho/distribution-table";
  if (tab === "sty") path = "/api/plots/phospho/sty-table";
  if (tab === "phosprotRegulation") path = "/api/plots/phospho/phosprot-regulation-table";

  const response = await fetch(buildPlotUrl(path, params), { signal: requestOptions.signal });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load phospho table"
    );
  }
  return data as PhosphoTableResponse;
}

export async function renderKseaVolcanoFromFiles(payload: {
  fileSt: File;
  fileTnc: File;
  pValueThreshold: number;
  header: boolean;
  condition1: string;
  condition2: string;
  condition1Control?: string;
  condition2Control?: string;
  annotateHits: boolean;
}): Promise<{ html: string; evidenceToken: string }> {
  const form = new FormData();
  form.append("fileSt", payload.fileSt);
  form.append("fileTnc", payload.fileTnc);
  form.append("pValueThreshold", String(payload.pValueThreshold));
  form.append("header", String(payload.header));
  form.append("condition1", payload.condition1);
  form.append("condition2", payload.condition2);
  form.append("condition1Control", payload.condition1Control ?? "");
  form.append("condition2Control", payload.condition2Control ?? "");
  form.append("annotateHits", String(payload.annotateHits));

  const response = await fetch(`${API_BASE}/api/plots/phospho/ksea-volcano.html`, {
    method: "POST",
    body: form,
  });
  const text = await response.text();
  if (!response.ok) {
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      throw new Error(parsed?.detail || "Failed to generate KSEA volcano");
    } catch {
      throw new Error(text || "Failed to generate KSEA volcano");
    }
  }
  return { html: text, evidenceToken: response.headers.get("X-Copylot-Evidence") ?? "" };
}

export async function getComparisonOptions(
  kind: AnnotationKind,
  dataSource: VisualizationDataSource = "log2",
  requestOptions: ApiRequestOptions = {}
): Promise<ComparisonOptionsResponse> {
  const response = await fetch(buildPlotUrl(`/api/plots/comparison/${kind}/options`, { dataSource }), {
    signal: requestOptions.signal,
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load comparison options"
    );
  }
  return data as ComparisonOptionsResponse;
}

export async function getComparisonTable(
  kind: AnnotationKind,
  tab: "pearson" | "venn",
  params?: Record<string, string | number | boolean>,
  requestOptions: ApiRequestOptions = {}
): Promise<ComparisonTableResponse> {
  const path =
    tab === "pearson"
      ? `/api/plots/comparison/${kind}/pearson-table`
      : `/api/plots/comparison/${kind}/venn-table`;

  const response = await fetch(buildPlotUrl(path, params), { signal: requestOptions.signal });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load comparison table"
    );
  }
  return data as ComparisonTableResponse;
}

export async function runPeptideCollapse(
  payload: PeptideCollapseRequest
): Promise<PeptideCollapseResponse> {
  const response = await fetch(`${API_BASE}/api/external/peptide-collapse/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to run peptide collapse"
    );
  }

  return data as PeptideCollapseResponse;
}

export async function getModelCapability(
  provider: ChatProvider,
  model: string,
  endpoint?: string
): Promise<ModelCapabilityResponse> {
  const params = new URLSearchParams({ provider, model: model.trim() });
  if (provider === "ollama" && endpoint?.trim()) {
    params.set("endpoint", endpoint.trim());
  }
  const response = await fetch(`${API_BASE}/api/chat/model-capability?${params.toString()}`);
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to inspect model capabilities"
    );
  }
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  const level = Number(raw.level);
  return {
    provider,
    model: String(raw.model ?? model),
    level: level === 3 ? 3 : level === 2 ? 2 : 1,
    assessment: raw.assessment === "tested" ? "tested" : raw.assessment === "inferred" ? "inferred" : "unknown",
    label: raw.label === "High" ? "High" : raw.label === "Medium" ? "Medium" : "Low",
    contextTier:
      raw.contextTier === "extended"
        ? "extended"
        : raw.contextTier === "standard"
          ? "standard"
          : "compact",
    contextWindow: raw.contextWindow == null ? null : Number(raw.contextWindow),
    parameterCountB: raw.parameterCountB == null ? null : Number(raw.parameterCountB),
    supportsTools: raw.supportsTools == null ? null : Boolean(raw.supportsTools),
    supportsVision: raw.supportsVision == null ? null : Boolean(raw.supportsVision),
    source:
      raw.source === "metadata"
        ? "metadata"
        : raw.source === "model_name"
          ? "model_name"
          : raw.source === "configured"
            ? "configured"
            : "fallback",
    reason: String(raw.reason ?? "Capability estimate unavailable"),
  };
}

export async function runPeptideCollapseFile(
  file: File,
  options: Pick<PeptideCollapseRequest, "cutoff">
): Promise<{ blob: Blob; filename: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("cutoff", String(options.cutoff));

  const response = await fetch(`${API_BASE}/api/external/peptide-collapse/upload`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const data = await parseJson(response);
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to run peptide collapse"
    );
  }

  const blob = await response.blob();
  const filename = resolveDownloadFilename(response, "peptide_collapsed.tsv");
  return { blob, filename };
}

export async function getSummaryTables(): Promise<SummaryTablesResponse> {
  const response = await fetch(`${API_BASE}/api/summary/tables`);
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load summary tables"
    );
  }
  return data as SummaryTablesResponse;
}

export async function generateSummaryReport(
  payload: SummaryReportRequest
): Promise<SummaryReportResponse> {
  const response = await fetch(`${API_BASE}/api/summary/report`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to generate summary report"
    );
  }
  return data as SummaryReportResponse;
}

export function buildPlotUrl(path: string, params?: Record<string, string | number | boolean>) {
  const base = `${API_BASE}${path}`;
  const query = new URLSearchParams();
  if (params) {
    const normalizedParams =
      path.startsWith("/api/plots/") || path.startsWith("/api/analysis/")
        ? normalizePlotSizeParams(params)
        : params;
    Object.entries(normalizedParams).forEach(([key, value]) => {
      query.set(key, String(value));
    });
  }
  if (!query.has("advanced") && (path.startsWith("/api/plots/") || path.startsWith("/api/analysis/"))) {
    const advanced = getActiveAdvancedPlotSettingsJson();
    if (advanced) {
      query.set("advanced", advanced);
    }
  }
  query.set("_dsn", String(DATASET_SCOPE_NONCE));

  const suffix = query.toString();
  return suffix ? `${base}?${suffix}` : base;
}
