import type {
  ContextMode,
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
  PhosphoOptionsResponse,
  PhosphoTableResponse,
  PeptideCoverageResponse,
  PeptideMetadataResponse,
  PeptideMetadataGenerateRequest,
  PeptideOverviewResponse,
  PeptideQuantityOptionsResponse,
  PeptidePathResponse,
  PeptideSpecies,
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
  DataSource,
  VolcanoControlRequest,
  VolcanoResultResponse,
  VolcanoRequest,
} from "./types";
import { DATA_SOURCE_LABELS } from "./types";
import { getActiveAdvancedPlotSettingsJson } from "./appSettings";
import { syncSummaryReportStateWithDatasets } from "./reportState";
import { emitDatasetStateChanged } from "./datasetEvents";
import { normalizePlotSizeParams } from "./plotLimits";
import { isAnalysisMutation, unsavedAnalysis } from "./unsavedAnalysis";
import { TAB_API_BASE as API_BASE } from "./tabSession";

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

/**
 * The message in an error response body, whatever shape FastAPI gave it.
 *
 * A handler's own error is `{"detail": "…"}`. A validation failure (422) is
 * `{"detail": [{"loc": …, "msg": "…"}, …]}`, and `String()` of that array is
 * "[object Object]" -- which is what every page showed for a p-value of 0.
 */
export function apiErrorMessage(data: unknown, fallback: string): string {
  if (!data || typeof data !== "object" || !("detail" in data)) return fallback;
  const detail = (data as { detail: unknown }).detail;
  if (typeof detail === "string") return detail.trim() || fallback;
  const items = Array.isArray(detail) ? detail : [detail];
  const messages = items
    .map((item) =>
      typeof item === "string"
        ? item
        : item && typeof item === "object" && "msg" in item && typeof (item as { msg: unknown }).msg === "string"
          ? (item as { msg: string }).msg
          : ""
    )
    .map((message) => message.trim())
    .filter(Boolean);
  return [...new Set(messages)].slice(0, 3).join("; ") || fallback;
}

export type AssistantView = {
  module: string; workflow: string; mode: ContextMode;
  controls: import("./assistantControls").AssistantControl[];
  destinations: Record<string, string>;
};

export type AssistantResult = {
  usedEvidenceFallback?: boolean;
  stoppedEarly?: boolean;
  explainAfterChanges?: boolean;
  needsClarification?: boolean;
  // Changes allowed in this request at the model's assistant level.
  actionBudget?: number;
  finished?: boolean;
  reviewAfter?: boolean;
  model: string; answer: string; revision: number;
  actions: import("./assistantControls").AssistantAction[];
  evidence: { tool: string; status: string; text: string }[];
};

// A progress poll never raises: a missed poll only leaves the previous line on screen.
export function getAssistantProgress(progressId: string): Promise<{ phase: string; tokens: number; seconds: number; calls: number }> {
  const unknown = { phase: "unknown", tokens: 0, seconds: 0, calls: 0 };
  return fetch(`${API_BASE}/api/chat/assistant-progress/${encodeURIComponent(progressId)}`)
    .then(response => (response.ok ? response.json() : unknown))
    .catch(() => unknown);
}

export async function assistantStep(
  payload: { message: string; messages?: ChatMessage[]; provider?: ChatProvider; model?: string; gpuEnabled?: boolean; apiKey?: string; ollamaUrl?: string; localServerUrl?: string; assistantLevel?: "auto" | "basic" | "standard" | "advanced"; plotImage?: string; progressId?: string; reviewing?: boolean; savedStyles?: string[]; view: AssistantView; receipts: string[]; notes?: string[]; answerOnly?: boolean; conversationState?: import("./assistantConversation").ConversationState | null },
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

type RequestOptions = Omit<RequestInit, "body"> & {
  /** Sent as the JSON body; the content type is set here, not at the call site. */
  json?: unknown;
  body?: BodyInit | null;
  /** What to raise when the error body carries no usable `detail`. */
  fallback: string;
};

/**
 * One request, one error path.
 *
 * Every client below used to spell out the same four steps -- fetch, parse the
 * body, test `response.ok`, throw `apiErrorMessage(...)`. That is why the 422
 * fix (a validation body is a list of objects, not a string) had to be applied
 * in every one of them, and why "[object Object]" survived for so long. The
 * steps live here now; a client keeps only its URL, its payload and the shape
 * of its result.
 */
async function requestResponse(url: string, { json, body, headers, fallback, ...init }: RequestOptions) {
  const response = await fetch(url, {
    ...init,
    headers: json === undefined ? headers : { "Content-Type": "application/json", ...headers },
    body: json === undefined ? body : JSON.stringify(json),
  });
  // The body is read here only to explain a failure; a caller that wants the
  // bytes (a download) gets the response with its body still unread.
  if (!response.ok) throw new Error(apiErrorMessage(await parseJson(response), fallback));
  return response;
}

/** The same request, with the JSON body parsed. */
async function requestUrl(url: string, options: RequestOptions) {
  return parseJson(await requestResponse(url, options));
}

/** The same request against an API path; `buildPlotUrl` callers use `requestUrl`. */
async function request(path: string, options: RequestOptions) {
  return requestUrl(`${API_BASE}${path}`, options);
}

export async function getViewerAuthStatus(): Promise<ViewerAuthStatusResponse> {
  const data = await request(`/api/viewer/auth/status`, { fallback: "Failed to load viewer auth status" });
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    enabled: Boolean(raw.enabled),
    authenticated: Boolean(raw.authenticated),
    project: raw.project == null ? null : String(raw.project),
    projectLabel: raw.projectLabel == null ? null : String(raw.projectLabel),
  };
}

export async function loginViewer(password: string): Promise<ViewerAuthLoginResponse> {
  const data = await request(`/api/viewer/auth/login`, {
    method: "POST",
    json: { password },
    fallback: "Viewer login failed",
  });
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    ok: Boolean(raw.ok),
    project: String(raw.project ?? ""),
    projectLabel: String(raw.projectLabel ?? raw.project ?? ""),
  };
}

export async function getRRuntimeStatus(refresh = false): Promise<RRuntimeStatusResponse> {
  const suffix = refresh ? "?refresh=1" : "";
  const data = await request(`/api/runtime/r${suffix}`, {
    cache: refresh ? "no-store" : "default",
    fallback: "Failed to detect R runtime",
  });
  return data as RRuntimeStatusResponse;
}

export async function getNormalizationCapability(
  refresh = false
): Promise<NormalizationCapabilityResponse> {
  const suffix = refresh ? "?refresh=1" : "";
  const data = await request(`/api/runtime/normalization${suffix}`, {
    cache: refresh ? "no-store" : "default",
    fallback: "Failed to detect normalization capabilities",
  });
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
  const data = await request(`/api/viewer/auth/qr-login`, {
    method: "POST",
    json: { token },
    fallback: "Viewer QR login failed",
  });
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    ok: Boolean(raw.ok),
    project: String(raw.project ?? ""),
    projectLabel: String(raw.projectLabel ?? raw.project ?? ""),
  };
}

export async function logoutViewer(): Promise<void> {
  await request(`/api/viewer/auth/logout`, { method: "POST", fallback: "Viewer logout failed" });
}

export async function getToolAuthStatus(): Promise<ToolAuthStatusResponse> {
  const data = await request(`/api/tool/auth/status`, { fallback: "Failed to load tool auth status" });
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    enabled: Boolean(raw.enabled),
    authenticated: Boolean(raw.authenticated),
  };
}

export async function loginTool(password: string): Promise<ToolAuthLoginResponse> {
  const data = await request(`/api/tool/auth/login`, {
    method: "POST",
    json: { password },
    fallback: "Tool login failed",
  });
  return { ok: Boolean((data as Record<string, unknown> | null)?.ok) };
}

export async function loginToolLink(token: string): Promise<ToolAuthLoginResponse> {
  const data = await request(`/api/tool/auth/link-login`, {
    method: "POST",
    json: { token },
    fallback: "Tool access link failed",
  });
  return { ok: Boolean((data as Record<string, unknown> | null)?.ok) };
}

export async function logoutTool(): Promise<void> {
  await request(`/api/tool/auth/logout`, { method: "POST", fallback: "Tool logout failed" });
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

  const data = await request(`/api/datasets/upload`, { method: "POST", body: form, fallback: "Upload failed" });

  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
  return data as DatasetPreviewResponse;
}

export async function saveTableDatasetPath(
  path: string,
  kind: Extract<DatasetKind, "protein" | "phospho" | "phosprot">,
  packageName?: string
): Promise<DatasetPreviewResponse> {
  const data = await request(`/api/datasets/table-path`, {
    method: "POST",
    json: { path, kind, packageName: packageName?.trim() || null },
    fallback: "Saving dataset path failed",
  });

  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
  return data as DatasetPreviewResponse;
}

function resolveDownloadFilename(response: Response, fallback: string): string {
  const disposition = response.headers.get("content-disposition") || "";
  // The real name, when it is not plain ASCII, is in filename* (RFC 5987).
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encoded?.[1]) {
    try {
      const decoded = decodeURIComponent(encoded[1].trim());
      if (decoded) return decoded;
    } catch {
      // fall through to the ASCII name
    }
  }
  const match = disposition.match(/filename="?([^";]+)"?/i);
  if (!match || !match[1]) return fallback;
  return match[1].trim() || fallback;
}

export async function downloadRestoreState(
  uiState: Record<string, unknown>,
  options: { portable?: boolean } = {}
): Promise<{ blob: Blob; filename: string }> {
  const response = await requestResponse(`${API_BASE}/api/restore/export`, {
    method: "POST",
    json: { uiState, portable: options.portable ?? false },
    fallback: "Failed to export restore state",
  });
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
      apiErrorMessage(data, "Failed to import restore state")
    );
  }

  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
  return data as RestoreImportResponse;
}

export async function resetBrowserSessionState(): Promise<void> {
  await request(`/api/restore/browser-session-reset`, {
    method: "POST",
    fallback: "Failed to reset browser session state",
  });
}

export async function savePeptidePath(path: string, packageName?: string): Promise<PeptidePathResponse> {
  const data = await request(`/api/datasets/peptide-path`, {
    method: "POST",
    json: { path, packageName: packageName?.trim() || null },
    fallback: "Saving peptide path failed",
  });

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

  const data = await request(`/api/datasets/peptide-file`, {
    method: "POST",
    body: form,
    fallback: "Saving peptide file failed",
  });

  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
  return data as PeptidePathResponse;
}

export async function getCurrentDatasets(
  requestOptions: ApiRequestOptions = {}
): Promise<CurrentDatasetsResponse> {
  const data = await request(`/api/datasets/current`, {
    signal: requestOptions.signal,
    fallback: "Failed to load current datasets",
  });

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

export async function createDatasetPackage(packageName: string): Promise<CurrentDatasetsResponse> {
  const data = await request(`/api/datasets/packages/create`, {
    method: "POST",
    json: { packageName },
    fallback: "Failed to create dataset package",
  });
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
  const data = await request(`/api/datasets/packages/rename`, {
    method: "POST",
    json: { oldName, newName },
    fallback: "Failed to rename dataset package",
  });
  const payload = data as CurrentDatasetsResponse;
  syncSummaryReportStateWithDatasets(payload);
  bumpDatasetScopeNonce();
  emitDatasetStateChanged(payload);
  return payload;
}

export async function setActiveDatasetPackage(packageName: string): Promise<CurrentDatasetsResponse> {
  const data = await request(`/api/datasets/active`, {
    method: "POST",
    json: { packageName },
    fallback: "Failed to switch dataset package",
  });

  const payload = data as CurrentDatasetsResponse;
  syncSummaryReportStateWithDatasets(payload);
  bumpDatasetScopeNonce();
  emitDatasetStateChanged(payload);
  return payload;
}

export async function createMetadataProfile(
  profileName: string
): Promise<CurrentDatasetsResponse> {
  const data = await request(`/api/datasets/metadata/profiles/create`, {
    method: "POST",
    json: { profileName },
    fallback: "Failed to create metadata profile",
  });
  const payload = data as CurrentDatasetsResponse;
  syncSummaryReportStateWithDatasets(payload);
  bumpDatasetScopeNonce();
  emitDatasetStateChanged(payload);
  return payload;
}

export async function deleteMetadataProfile(
  profileName: string
): Promise<CurrentDatasetsResponse> {
  const data = await request(`/api/datasets/metadata/profiles/delete`, {
    method: "DELETE",
    json: { profileName },
    fallback: "Failed to delete metadata profile",
  });
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
  const data = await request(`/api/datasets/metadata/profiles/rename`, {
    method: "POST",
    json: { oldName, newName },
    fallback: "Failed to rename metadata profile",
  });
  const payload = data as CurrentDatasetsResponse;
  syncSummaryReportStateWithDatasets(payload);
  bumpDatasetScopeNonce();
  emitDatasetStateChanged(payload);
  return payload;
}

export async function setActiveMetadataProfile(
  profileName: string
): Promise<CurrentDatasetsResponse> {
  const data = await request(`/api/datasets/metadata/profiles/active`, {
    method: "POST",
    json: { profileName },
    fallback: "Failed to switch metadata profile",
  });
  const payload = data as CurrentDatasetsResponse;
  syncSummaryReportStateWithDatasets(payload);
  bumpDatasetScopeNonce();
  emitDatasetStateChanged(payload);
  return payload;
}

export async function getPeptideOverview(
  requestOptions: ApiRequestOptions = {}
): Promise<PeptideOverviewResponse> {
  const data = await request(`/api/peptide/overview`, {
    signal: requestOptions.signal,
    fallback: "Failed to load peptide overview",
  });

  return data as PeptideOverviewResponse;
}

export async function getCurrentPeptideMetadata(): Promise<PeptideMetadataResponse | null> {
  const response = await fetch(`${API_BASE}/api/peptide/metadata/current`);
  const data = await parseJson(response);

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new Error(
      apiErrorMessage(data, "Failed to load peptide metadata")
    );
  }

  return data as PeptideMetadataResponse;
}

export async function getPeptideSequenceCoverage(
  species: PeptideSpecies,
  protein: string,
  chunkSize: number,
  requestOptions: ApiRequestOptions = {}
): Promise<PeptideCoverageResponse> {
  const data = await requestUrl(buildPlotUrl("/api/peptide/sequence-coverage", { species, protein, chunkSize }), {
    signal: requestOptions.signal,
    fallback: "Failed to calculate peptide sequence coverage",
  });

  return data as PeptideCoverageResponse;
}

export async function generateAnnotation(
  payload: AnnotationGenerateRequest
): Promise<AnnotationResultResponse> {
  const data = await request(`/api/annotations/generate`, {
    method: "POST",
    json: payload,
    fallback: "Failed to generate annotation",
  });

  // Every matrix downstream of this call is different now, so the plot and
  // table URLs must be different too: `_dsn` is what makes them so.
  bumpDatasetScopeNonce();
  return data as AnnotationResultResponse;
}

export async function generatePeptideMetadata(
  payload: PeptideMetadataGenerateRequest
): Promise<PeptideMetadataResponse> {
  const data = await request(`/api/peptide/metadata/generate`, {
    method: "POST",
    json: payload,
    fallback: "Failed to generate peptide metadata",
  });

  // Every matrix downstream of this call is different now, so the plot and
  // table URLs must be different too: `_dsn` is what makes them so.
  bumpDatasetScopeNonce();
  return data as PeptideMetadataResponse;
}

export async function detectAnnotationLog2Scale(
  payload: Log2DetectionRequest
): Promise<Log2DetectionResponse> {
  const data = await request(`/api/annotations/log2-detect`, {
    method: "POST",
    json: payload,
    fallback: "Failed to detect intensity scale",
  });
  return data as Log2DetectionResponse;
}

export async function getCurrentAnnotation(
  kind: AnnotationKind,
  requestOptions: ApiRequestOptions = {}
): Promise<AnnotationResultResponse> {
  const data = await request(`/api/annotations/current/${kind}`, {
    signal: requestOptions.signal,
    fallback: "Failed to fetch current annotation",
  });

  return data as AnnotationResultResponse;
}

export async function downloadCurrentAnnotationFilteredData(
  kind: AnnotationKind
): Promise<{ blob: Blob; filename: string }> {
  const response = await requestResponse(`${API_BASE}/api/annotations/current/${kind}/filtered/download`, {
    fallback: "Failed to download filtered annotation data",
  });
  const blob = await response.blob();
  const filename = resolveDownloadFilename(response, `${kind}_filtered_data_full.csv`);
  return { blob, filename };
}

export async function downloadCurrentAnnotationSourceData(
  kind: AnnotationKind
): Promise<{ blob: Blob; filename: string }> {
  const response = await requestResponse(`${API_BASE}/api/annotations/current/${kind}/source/download`, {
    fallback: "Failed to download non-filtered annotation data",
  });
  const blob = await response.blob();
  const filename = resolveDownloadFilename(response, `${kind}_data_full.csv`);
  return { blob, filename };
}

export async function downloadCurrentAnnotationMetadataData(
  kind: AnnotationKind
): Promise<{ blob: Blob; filename: string }> {
  const response = await requestResponse(`${API_BASE}/api/annotations/current/${kind}/metadata/download`, {
    fallback: "Failed to download metadata annotation data",
  });
  const blob = await response.blob();
  const filename = resolveDownloadFilename(response, `${kind}_metadata_full.csv`);
  return { blob, filename };
}

export async function updateAnnotationPairing(
  payload: PairingUpdateRequest
): Promise<AnnotationResultResponse> {
  const data = await request(`/api/annotations/pairing`, {
    method: "PUT",
    json: payload,
    fallback: "Failed to save sample pairing",
  });
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

  const data = await request(`/api/annotations/metadata/upload`, {
    method: "POST",
    body: form,
    fallback: "Failed to upload metadata",
  });

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
      apiErrorMessage(data, "Failed to load uploaded metadata")
    );
  }

  return data as MetadataUploadResponse;
}

export async function runImputation(
  payload: ImputationRunRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<ImputationResultResponse> {
  const data = await request(`/api/data-tools/imputation/run`, {
    method: "POST",
    json: payload,
    signal: requestOptions.signal,
    fallback: "Failed to run imputation",
  });
  // Every matrix downstream of this call is different now, so the plot and
  // table URLs must be different too: `_dsn` is what makes them so.
  bumpDatasetScopeNonce();
  return data as ImputationResultResponse;
}

export async function downloadImputationCsv(
  payload: ImputationRunRequest
): Promise<Blob> {
  const response = await requestResponse(`${API_BASE}/api/data-tools/imputation/download`, {
    method: "POST",
    json: payload,
    fallback: "Failed to download imputed CSV",
  });

  return response.blob();
}

export async function getDistributionSummary(
  kind: AnnotationKind,
  requestOptions: ApiRequestOptions = {}
): Promise<DistributionSummaryResponse> {
  const data = await request(`/api/data-tools/distribution/${kind}`, {
    signal: requestOptions.signal,
    fallback: "Failed to load distribution summary",
  });
  return data as DistributionSummaryResponse;
}

export async function runIdTranslation(
  payload: IdTranslationRequest
): Promise<IdTranslationResponse> {
  const data = await request(`/api/data-tools/id-translation/run`, {
    method: "POST",
    json: payload,
    fallback: "Failed to translate IDs",
  });
  return data as IdTranslationResponse;
}

export async function downloadIdTranslation(
  payload: IdTranslationRequest
): Promise<Blob> {
  const response = await requestResponse(`${API_BASE}/api/data-tools/id-translation/download`, {
    method: "POST",
    json: payload,
    fallback: "Failed to download translated table",
  });

  return response.blob();
}

export async function aggregatePhosprot(
  mode: PhosprotAggregationMode,
  source: PhosprotAggregationSource,
  localizationCutoff = 0
): Promise<AnnotationResultResponse> {
  const data = await request(`/api/annotations/phosprot/aggregate`, {
    method: "POST",
    json: { mode, source, localizationCutoff },
    fallback: "Failed to aggregate phosphoprotein dataset",
  });
  // Every matrix downstream of this call is different now, so the plot and
  // table URLs must be different too: `_dsn` is what makes them so.
  bumpDatasetScopeNonce();
  return data as AnnotationResultResponse;
}

export async function getConditionPalette(
  kind: AnnotationKind,
  requestOptions: ApiRequestOptions = {}
): Promise<ConditionPaletteResponse> {
  const data = await request(`/api/data-tools/condition-colors/${kind}`, {
    signal: requestOptions.signal,
    fallback: "Failed to load condition colors",
  });
  return data as ConditionPaletteResponse;
}

export async function setConditionPalette(
  kind: AnnotationKind,
  palette: Record<string, string>
): Promise<ConditionPaletteResponse> {
  const data = await request(`/api/data-tools/condition-colors/${kind}`, {
    method: "POST",
    json: { palette },
    fallback: "Failed to save condition colors",
  });
  // Every matrix downstream of this call is different now, so the plot and
  // table URLs must be different too: `_dsn` is what makes them so.
  bumpDatasetScopeNonce();
  return data as ConditionPaletteResponse;
}

export async function getCompletenessTables(
  kind: AnnotationKind,
  params?: Record<string, string | number | boolean>,
  requestOptions: ApiRequestOptions = {}
): Promise<CompletenessTablesResponse> {
  const data = await requestUrl(buildPlotUrl(`/api/data-tools/completeness/${kind}/tables`, params), {
    signal: requestOptions.signal,
    fallback: "Failed to load completeness tables",
  });
  return data as CompletenessTablesResponse;
}

export async function getQcPlotOptions(
  kind: AnnotationKind,
  requestOptions: ApiRequestOptions = {}
): Promise<QcPlotOptionsResponse> {
  const data = await request(`/api/plots/qc/${kind}/options`, {
    signal: requestOptions.signal,
    fallback: "Failed to load QC plot options",
  });
  const payload = data as Partial<QcPlotOptionsResponse>;
  return {
    conditions: Array.isArray(payload.conditions) ? payload.conditions : [],
    imputedAvailable: Boolean(payload.imputedAvailable),
    samples: Array.isArray(payload.samples) ? payload.samples : [],
    sampleLabels: payload.sampleLabels ?? {},
    sampleLabelsWithId: payload.sampleLabelsWithId ?? {},
    availableDataSources: Array.isArray(payload.availableDataSources)
      ? payload.availableDataSources
      : (["data"] as DataSource[]),
    defaultDataSource: payload.defaultDataSource ?? "data",
    centredPhosprotValues: Boolean(payload.centredPhosprotValues),
  };
}

export async function getPeptideQuantityOptions(
  requestOptions: ApiRequestOptions = {}
): Promise<PeptideQuantityOptionsResponse> {
  const data = await request(`/api/peptide/quantity-options`, {
    signal: requestOptions.signal,
    fallback: "Failed to load peptide abundance columns",
  });
  const payload = data as Partial<PeptideQuantityOptionsResponse>;
  return {
    columns: Array.isArray(payload.columns) ? payload.columns : [],
    defaultColumn: typeof payload.defaultColumn === "string" ? payload.defaultColumn : null,
    requiresSelection: Boolean(payload.requiresSelection),
  };
}

/** Every control that moves a point in the PCA projection.
 *
 * The summary names the groups that got no ellipse, and whether a group has
 * one depends on where its points land -- so the notice has to be computed
 * from the same settings the figure was drawn with, not from the defaults.
 */
export type QcPcaFeatureQuery = {
  dataSource: string;
  plotDim: string;
  addEllipses: boolean;
  method: string;
  scaling: string;
  colorBy: string;
  clusterMethod: string;
  clusterCount: number;
  dbscanEpsFactor: number;
  dbscanMinSamples: number;
  umapNNeighbors: number;
  umapMinDist: number;
  tsnePerplexity: number;
  tsneLearningRate: number;
  randomState: number;
};

export async function getQcPcaFeatures(
  kind: AnnotationKind,
  params: QcPcaFeatureQuery,
  requestOptions: ApiRequestOptions = {}
): Promise<QcPcaFeatureSummary> {
  const query = new URLSearchParams({
    dataSource: params.dataSource,
    plotDim: params.plotDim,
    addEllipses: String(params.addEllipses),
    method: params.method,
    scaling: params.scaling,
    colorBy: params.colorBy,
    clusterMethod: params.clusterMethod,
    clusterCount: String(params.clusterCount),
    dbscanEpsFactor: String(params.dbscanEpsFactor),
    dbscanMinSamples: String(params.dbscanMinSamples),
    umapNNeighbors: String(params.umapNNeighbors),
    umapMinDist: String(params.umapMinDist),
    tsnePerplexity: String(params.tsnePerplexity),
    tsneLearningRate: String(params.tsneLearningRate),
    randomState: String(params.randomState),
  });
  const data = await request(`/api/plots/qc/${kind}/pca-features?${query.toString()}`, {
    signal: requestOptions.signal,
    fallback: "Failed to load PCA feature summary",
  });
  const payload = data as Partial<QcPcaFeatureSummary>;
  return {
    featuresTotal: Number(payload.featuresTotal ?? 0),
    featuresComplete: Number(payload.featuresComplete ?? 0),
    featuresUsed: Number(payload.featuresUsed ?? 0),
    featuresRequired: Number(payload.featuresRequired ?? 2),
    ellipseSkippedGroups: Array.isArray(payload.ellipseSkippedGroups)
      ? payload.ellipseSkippedGroups.map((group) => String(group))
      : [],
    smallSampleNotice: typeof payload.smallSampleNotice === "string" ? payload.smallSampleNotice : null,
    dbscan:
      payload.dbscan && typeof payload.dbscan === "object"
        ? {
            epsFactor: Number(payload.dbscan.epsFactor ?? 0),
            medianSampleDistance: Number(payload.dbscan.medianSampleDistance ?? 0),
            epsEffective: Number(payload.dbscan.epsEffective ?? 0),
          }
        : null,
  };
}

export async function getQcTable(
  kind: AnnotationKind,
  tab: "coverage" | "boxplot" | "cv",
  params?: Record<string, string | number | boolean>,
  requestOptions: ApiRequestOptions = {}
): Promise<QcTableResponse> {
  const path = `/api/plots/qc/${kind}/${tab}-table`;

  const data = await requestUrl(buildPlotUrl(path, params), {
    signal: requestOptions.signal,
    fallback: "Failed to load QC table",
  });
  return data as QcTableResponse;
}

export async function getStatisticalOptions(
  kind: AnnotationKind,
  requestOptions: ApiRequestOptions = {}
): Promise<StatisticalOptionsResponse> {
  const data = await request(`/api/stats/options/${kind}`, {
    signal: requestOptions.signal,
    fallback: "Failed to load statistical options",
  });
  const payloadRaw = data as Partial<StatisticalOptionsResponse>;
  return {
    kind: (payloadRaw.kind as AnnotationKind) ?? kind,
    sourceUsed: payloadRaw.sourceUsed ?? "raw",
    imputedAvailable: Boolean(payloadRaw.imputedAvailable),
    availableDataSources: Array.isArray(payloadRaw.availableDataSources)
      ? payloadRaw.availableDataSources
      : (["data"] as DataSource[]),
    defaultDataSource: payloadRaw.defaultDataSource ?? "data",
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

export async function getVolcanoNotebookTable(kind: AnnotationKind, snapshot: string, signal: AbortSignal): Promise<VolcanoResultResponse> {
  return await requestUrl(buildPlotUrl(`/api/plots/stats/${kind}/volcano-table`, { snapshot }), {
    signal, fallback: "Failed to load the captured volcano table",
  }) as VolcanoResultResponse;
}

export async function getAnovaNotebookTables(kind: AnnotationKind, snapshot: string, signal: AbortSignal): Promise<AnovaResultResponse> {
  return await requestUrl(buildPlotUrl(`/api/plots/stats/${kind}/anova-tables`, { snapshot }), {
    signal, fallback: "Failed to load the captured ANOVA tables",
  }) as AnovaResultResponse;
}

export async function getOraNotebookTables(kind: AnnotationKind, direction: string, snapshot: string, signal: AbortSignal): Promise<EnrichmentResultResponse> {
  return await requestUrl(buildPlotUrl(`/api/plots/stats/${kind}/ora/${direction}/tables`, { snapshot }), {
    signal, fallback: "Failed to load the captured ORA tables",
  }) as EnrichmentResultResponse;
}

export async function runVolcanoAnalysis(
  payload: VolcanoRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<VolcanoResultResponse> {
  const data = await request(`/api/stats/volcano/run`, {
    method: "POST",
    json: payload,
    signal: requestOptions.signal,
    fallback: "Failed to run volcano analysis",
  });
  return data as VolcanoResultResponse;
}

export async function runVolcanoControlAnalysis(
  payload: VolcanoControlRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<VolcanoResultResponse> {
  const data = await request(`/api/stats/volcano-control/run`, {
    method: "POST",
    json: payload,
    signal: requestOptions.signal,
    fallback: "Failed to run control volcano analysis",
  });
  return data as VolcanoResultResponse;
}

export async function runAnovaAnalysis(
  payload: AnovaRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<AnovaResultResponse> {
  const data = await request(`/api/stats/anova/run`, {
    method: "POST",
    json: payload,
    signal: requestOptions.signal,
    fallback: "Failed to run ANOVA analysis",
  });
  return data as AnovaResultResponse;
}

export async function runEnrichmentAnalysis(
  payload: EnrichmentRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<EnrichmentResultResponse> {
  const data = await request(`/api/stats/ora/run`, {
    method: "POST",
    json: payload,
    signal: requestOptions.signal,
    fallback: "Failed to run enrichment analysis",
  });
  return data as EnrichmentResultResponse;
}

export async function runListEnrichmentAnalysis(
  payload: ListEnrichmentRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<ListEnrichmentResultResponse> {
  const data = await request(`/api/stats/ora/list/run`, {
    method: "POST",
    json: payload,
    signal: requestOptions.signal,
    fallback: "Failed to run list enrichment analysis",
  });
  return data as ListEnrichmentResultResponse;
}

export async function runAnalysisVolcanoData(
  payload: AnalysisVolcanoRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<AnalysisVolcanoResponse> {
  const data = await request(`/api/analysis/volcano/data`, {
    method: "POST",
    json: payload,
    signal: requestOptions.signal,
    fallback: "Failed to load analysis volcano data",
  });
  return data as AnalysisVolcanoResponse;
}

function normalizeCloudAiConsentStatus(value: unknown): CloudAiConsentStatus {
  const raw = value && typeof value === "object" ? (value as Record<string, unknown>) : {};
  const provider: ChatProvider =
    raw.provider === "openai" || raw.provider === "anthropic" || raw.provider === "gemini" || raw.provider === "openai_compatible"
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
  const data = await request(`/api/chat/cloud-consent/${encodeURIComponent(provider)}`, {
    fallback: "Failed to load cloud AI consent status",
  });
  return normalizeCloudAiConsentStatus(data);
}

export async function grantCloudAiConsent(
  provider: ChatProvider,
  disclosureVersion: string
): Promise<CloudAiConsentStatus> {
  const data = await request(`/api/chat/cloud-consent/${encodeURIComponent(provider)}/grant`, {
    method: "POST",
    json: { disclosureVersion },
    fallback: "Failed to confirm cloud AI consent",
  });
  return normalizeCloudAiConsentStatus(data);
}

export async function revokeCloudAiConsent(provider: ChatProvider): Promise<CloudAiConsentStatus> {
  const data = await request(`/api/chat/cloud-consent/${encodeURIComponent(provider)}/revoke`, {
    method: "POST",
    fallback: "Failed to revoke cloud AI consent",
  });
  return normalizeCloudAiConsentStatus(data);
}

export async function getOllamaGpuStatus(endpoint?: string): Promise<OllamaGpuStatusResponse> {
  const url = endpoint?.trim()
    ? `${API_BASE}/api/chat/gpu-status?endpoint=${encodeURIComponent(endpoint.trim())}`
    : `${API_BASE}/api/chat/gpu-status`;
  const data = await requestUrl(url, { fallback: "Failed to load Ollama GPU status" });
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

export type AiOperatorPolicy = { providers: string[]; models: Record<string, string[]>; modelManagement: boolean };

/** The server's default model per cloud provider, what the operator allows, and
 * the operator's preset local OpenAI-compatible server ("" when none). */
export async function getProviderDefaults(): Promise<{ models: Record<string, string>; policy: AiOperatorPolicy; localServerUrl: string }> {
  const data = await requestUrl(`${API_BASE}/api/chat/provider-defaults`, { fallback: "Failed to load default models" });
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  const models = Object.fromEntries(
    Object.entries((raw.models ?? {}) as Record<string, unknown>).map(([provider, model]) => [provider, String(model ?? "")]),
  );
  const policy = (raw.policy ?? {}) as Record<string, unknown>;
  return {
    models,
    policy: {
      providers: Array.isArray(policy.providers) ? policy.providers.map(String) : ["ollama", "openai_compatible", "openai", "anthropic", "gemini"],
      models: Object.fromEntries(Object.entries((policy.models ?? {}) as Record<string, unknown>)
        .map(([provider, list]) => [provider, Array.isArray(list) ? list.map(String) : []])),
      modelManagement: policy.modelManagement !== false,
    },
    localServerUrl: String(raw.localServerUrl ?? ""),
  };
}

/** Models of a local OpenAI-compatible server (llama.cpp, vLLM, LM Studio). A POST,
 * so a typed API key never travels in a URL. */
export async function getLocalServerModels(endpoint?: string, apiKey?: string): Promise<OllamaModelsResponse> {
  const data = await request(`/api/chat/local-models`, {
    method: "POST",
    json: { endpoint: endpoint?.trim() || null, apiKey: apiKey?.trim() || null },
    fallback: "Failed to load the local AI server's models",
  });
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    models: Array.isArray(raw.models) ? raw.models.map((item) => String(item)) : [],
    selectedModel: raw.selectedModel == null ? null : String(raw.selectedModel),
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map((item) => String(item)) : [],
  };
}

export async function getOllamaModels(endpoint?: string): Promise<OllamaModelsResponse> {
  const url = endpoint?.trim()
    ? `${API_BASE}/api/chat/models?endpoint=${encodeURIComponent(endpoint.trim())}`
    : `${API_BASE}/api/chat/models`;
  const data = await requestUrl(url, { fallback: "Failed to load Ollama models" });
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  return {
    models: Array.isArray(raw.models) ? raw.models.map((item) => String(item)) : [],
    selectedModel: raw.selectedModel == null ? null : String(raw.selectedModel),
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map((item) => String(item)) : [],
  };
}

export async function installOllamaModel(model: string, endpoint?: string): Promise<OllamaModelManageResponse> {
  const data = await request(`/api/chat/models/install`, {
    method: "POST",
    json: { model, endpoint: endpoint?.trim() || null },
    fallback: "Failed to install Ollama model",
  });
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
  const data = await request(`/api/chat/models/remove`, {
    method: "POST",
    json: { model, endpoint: endpoint?.trim() || null },
    fallback: "Failed to remove Ollama model",
  });
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
  const data = await request(`/api/stats/pathways`, {
    signal: requestOptions.signal,
    fallback: "Failed to load pathway options",
  });
  return data as PathwayOptionsResponse;
}

export async function runSimulationAnalysis(
  payload: SimulationRequest,
  requestOptions: ApiRequestOptions = {}
): Promise<SimulationResultResponse> {
  const data = await request(`/api/stats/simulation/run`, {
    method: "POST",
    json: payload,
    signal: requestOptions.signal,
    fallback: "Failed to run simulation",
  });
  return data as SimulationResultResponse;
}

export async function getSingleProteinOptions(
  kind: AnnotationKind,
  tab: "boxplot" | "lineplot" | "heatmap",
  identifier: "workflow" | "genes" = "workflow",
  dataSource: DataSource = "data",
  requestOptions: ApiRequestOptions = {}
): Promise<SingleProteinOptionsResponse> {
  const data = await requestUrl(buildPlotUrl(`/api/plots/single-protein/${kind}/options`, { tab, identifier, dataSource }), {
    signal: requestOptions.signal,
    fallback: "Failed to load single-protein options",
  });
  return data as SingleProteinOptionsResponse;
}

export async function getSingleProteinTable(
  kind: AnnotationKind,
  tab: "boxplot" | "lineplot" | "heatmap",
  params?: Record<string, string | number | boolean>,
  requestOptions: ApiRequestOptions = {}
): Promise<SingleProteinTableResponse> {
  const data = await requestUrl(buildPlotUrl(`/api/plots/single-protein/${kind}/${tab}-table`, params), {
    signal: requestOptions.signal,
    fallback: "Failed to load single-protein table",
  });
  return data as SingleProteinTableResponse;
}

/** What the lineplot says under itself about selected names that match no row. */
export async function getLineplotUnmatchedNotice(
  kind: AnnotationKind,
  params: { proteins: string; identifier: string; dataSource: string },
  requestOptions: ApiRequestOptions = {}
): Promise<string> {
  const data = await requestUrl(buildPlotUrl(`/api/plots/single-protein/${kind}/lineplot-unmatched`, params), {
    signal: requestOptions.signal,
    fallback: "Failed to check the lineplot selection",
  });
  return typeof (data as { notice?: unknown })?.notice === "string" ? (data as { notice: string }).notice : "";
}

export async function getPhosphoOptions(
  requestOptions: ApiRequestOptions = {}
): Promise<PhosphoOptionsResponse> {
  const data = await request(`/api/plots/phospho/options`, {
    signal: requestOptions.signal,
    fallback: "Failed to load phospho options",
  });
  const payloadRaw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  const available = payloadRaw.availableDataSources;
  const defaultSource = payloadRaw.defaultDataSource;
  if (
    !Array.isArray(available) ||
    !available.every(source => typeof source === "string" && Object.hasOwn(DATA_SOURCE_LABELS, source)) ||
    typeof defaultSource !== "string" || !Object.hasOwn(DATA_SOURCE_LABELS, defaultSource) ||
    (available.length > 0 && !available.includes(defaultSource))
  ) {
    throw new Error("Invalid phospho data-source options. Reload the app and try again.");
  }
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

  const data = await requestUrl(buildPlotUrl(path, params), {
    signal: requestOptions.signal,
    fallback: "Failed to load phospho table",
  });
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
    // Parsed apart from the throw: a `catch` around both used to swallow the
    // readable message it had just built and show the raw `{"detail": ...}`.
    let parsed: unknown;
    try {
      parsed = JSON.parse(text) as unknown;
    } catch {
      parsed = null;
    }
    throw new Error(
      parsed === null
        ? text || "Failed to generate Kinase Library volcano"
        : apiErrorMessage(parsed, "Failed to generate Kinase Library volcano")
    );
  }
  return { html: text, evidenceToken: response.headers.get("X-Copylot-Evidence") ?? "" };
}

export async function getComparisonOptions(
  kind: AnnotationKind,
  requestOptions: ApiRequestOptions = {}
): Promise<ComparisonOptionsResponse> {
  // Comparison is QC: it reads the data as loaded and takes no source.
  const data = await requestUrl(buildPlotUrl(`/api/plots/comparison/${kind}/options`, {}), {
    signal: requestOptions.signal,
    fallback: "Failed to load comparison options",
  });
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

  const data = await requestUrl(buildPlotUrl(path, params), {
    signal: requestOptions.signal,
    fallback: "Failed to load comparison table",
  });
  return data as ComparisonTableResponse;
}

export async function getModelCapability(
  provider: ChatProvider,
  model: string,
  endpoint?: string
): Promise<ModelCapabilityResponse> {
  const params = new URLSearchParams({ provider, model: model.trim() });
  if ((provider === "ollama" || provider === "openai_compatible") && endpoint?.trim()) {
    params.set("endpoint", endpoint.trim());
  }
  const data = await request(`/api/chat/model-capability?${params.toString()}`, {
    fallback: "Failed to inspect model capabilities",
  });
  const raw = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  const level = Number(raw.level);
  return {
    provider,
    model: String(raw.model ?? model),
    level: level === 3 ? 3 : level === 2 ? 2 : 1,
    assessment: raw.assessment === "tested" || raw.assessment === "observed" || raw.assessment === "configured"
      || raw.assessment === "inferred" ? raw.assessment : "unknown",
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
    levelName: raw.levelName === "Advanced" ? "Advanced" : raw.levelName === "Standard" ? "Standard" : "Basic",
    reasoning: Boolean(raw.reasoning),
    outputTokens: Number.isFinite(Number(raw.outputTokens)) ? Number(raw.outputTokens) : 1024,
  };
}

export async function runPeptideCollapseFile(
  file: File,
  options: { cutoff: number }
): Promise<{ blob: Blob; filename: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("cutoff", String(options.cutoff));

  const response = await requestResponse(`${API_BASE}/api/external/peptide-collapse/upload`, {
    method: "POST",
    body: form,
    fallback: "Failed to run peptide collapse",
  });

  const blob = await response.blob();
  const filename = resolveDownloadFilename(response, "peptide_collapsed.tsv");
  return { blob, filename };
}

export async function getSummaryTables(): Promise<SummaryTablesResponse> {
  const data = await request(`/api/summary/tables`, { fallback: "Failed to load summary tables" });
  return data as SummaryTablesResponse;
}

export async function generateSummaryReport(
  payload: SummaryReportRequest
): Promise<SummaryReportResponse> {
  const data = await request(`/api/summary/report`, {
    method: "POST",
    json: payload,
    fallback: "Failed to generate summary report",
  });
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

export type PhosphoLocalizationCutoff = { cutoff: number; available: boolean };

// The session-wide phosphosite localization probability cutoff. Every
// phosphosite module reads its matrix through the backend with this cutoff
// applied, so changing it is a dataset-state change: plot URLs get a new
// scope nonce and every page that listens for dataset changes reloads.
export async function getPhosphoLocalizationCutoff(): Promise<PhosphoLocalizationCutoff> {
  const data = await request(`/api/data-tools/phospho-localization-cutoff`, {
    fallback: "Failed to load the localization probability cutoff",
  });
  return data as PhosphoLocalizationCutoff;
}

export async function setPhosphoLocalizationCutoff(cutoff: number): Promise<PhosphoLocalizationCutoff> {
  const data = await request(`/api/data-tools/phospho-localization-cutoff`, {
    method: "POST",
    json: { cutoff },
    fallback: "Failed to set the localization probability cutoff",
  });
  bumpDatasetScopeNonce();
  emitDatasetStateChanged();
  return data as PhosphoLocalizationCutoff;
}
