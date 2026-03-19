import type {
  CurrentDatasetsResponse,
  DatasetPreviewResponse,
  DatasetKind,
  PeptidePathResponse,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function uploadDataset(
  file: File,
  kind: "protein" | "phospho"
): Promise<DatasetPreviewResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);

  const response = await fetch(`${API_BASE}/api/datasets/upload`, {
    method: "POST",
    body: form,
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Upload failed");
  }

  return data;
}

export async function savePeptidePath(
  path: string
): Promise<PeptidePathResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/peptide-path`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ path }),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Saving peptide path failed");
  }

  return data;
}

export async function getCurrentDatasets(): Promise<CurrentDatasetsResponse> {
  const response = await fetch(`${API_BASE}/api/datasets/current`);
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Failed to load current datasets");
  }

  return data;
}