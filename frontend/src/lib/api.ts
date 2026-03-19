import type {
  AnnotationGenerateRequest,
  AnnotationKind,
  AnnotationResultResponse,
  CompletenessTablesResponse,
  DistributionSummaryResponse,
  CurrentDatasetsResponse,
  DatasetPreviewResponse,
  DatasetKind,
  ImputationResultResponse,
  ImputationRunRequest,
  MetadataUploadResponse,
  PeptidePathResponse,
  QcSummaryResponse,
  QcPlotOptionsResponse,
  QcTableResponse,
  VerificationSummaryResponse,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function parseJson(response: Response) {
  const text = await response.text();
  if (!text) return null;

  try {
    return JSON.parse(text);
  } catch {
    throw new Error("Backend returned invalid JSON");
  }
}

export async function uploadDataset(
  file: File,
  kind: Extract<DatasetKind, "protein" | "phospho">
): Promise<DatasetPreviewResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);

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

  return data as DatasetPreviewResponse;
}

export async function savePeptidePath(path: string): Promise<PeptidePathResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/peptide-path`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path }),
  });

  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Saving peptide path failed"
    );
  }

  return data as PeptidePathResponse;
}

export async function getCurrentDatasets(): Promise<CurrentDatasetsResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/current`);
  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load current datasets"
    );
  }

  return data as CurrentDatasetsResponse;
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

export async function getCurrentAnnotation(
  kind: AnnotationKind
): Promise<AnnotationResultResponse> {
  const response = await fetch(`${API_BASE}/api/annotations/current/${kind}`);
  const data = await parseJson(response);

  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to fetch current annotation"
    );
  }

  return data as AnnotationResultResponse;
}

export async function uploadAnnotationMetadata(
  file: File,
  kind: AnnotationKind
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

  return data as MetadataUploadResponse;
}

export async function getUploadedAnnotationMetadata(
  kind: AnnotationKind
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

export async function clearUploadedAnnotationMetadata(kind: AnnotationKind): Promise<void> {
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
}

export async function runImputation(
  payload: ImputationRunRequest
): Promise<ImputationResultResponse> {
  const response = await fetch(`${API_BASE}/api/data-tools/imputation/run`, {
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
  kind: AnnotationKind
): Promise<DistributionSummaryResponse> {
  const response = await fetch(`${API_BASE}/api/data-tools/distribution/${kind}`);
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load distribution summary"
    );
  }
  return data as DistributionSummaryResponse;
}

export async function getVerificationSummary(
  kind: AnnotationKind
): Promise<VerificationSummaryResponse> {
  const response = await fetch(`${API_BASE}/api/data-tools/verification/${kind}`);
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load verification summary"
    );
  }
  return data as VerificationSummaryResponse;
}

export async function getCompletenessTables(
  kind: AnnotationKind,
  params?: Record<string, string | number | boolean>
): Promise<CompletenessTablesResponse> {
  const response = await fetch(buildPlotUrl(`/api/data-tools/completeness/${kind}/tables`, params));
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

export async function getQcPlotOptions(kind: AnnotationKind): Promise<QcPlotOptionsResponse> {
  const response = await fetch(`${API_BASE}/api/plots/qc/${kind}/options`);
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load QC plot options"
    );
  }
  return data as QcPlotOptionsResponse;
}

export async function getQcTable(
  kind: AnnotationKind,
  tab: "coverage" | "boxplot" | "cv",
  params?: Record<string, string | number | boolean>
): Promise<QcTableResponse> {
  let path = `/api/plots/qc/${kind}/${tab}-table`;
  if (tab === "coverage") path = `/api/plots/qc/${kind}/coverage-table`;
  if (tab === "boxplot") path = `/api/plots/qc/${kind}/boxplot-table`;
  if (tab === "cv") path = `/api/plots/qc/${kind}/cv-table`;

  const response = await fetch(buildPlotUrl(path, params));
  const data = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      (data && typeof data === "object" && "detail" in data && String(data.detail)) ||
        "Failed to load QC table"
    );
  }
  return data as QcTableResponse;
}

export function buildPlotUrl(path: string, params?: Record<string, string | number | boolean>) {
  const base = `${API_BASE}${path}`;
  if (!params) return base;

  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    query.set(key, String(value));
  });

  const suffix = query.toString();
  return suffix ? `${base}?${suffix}` : base;
}
