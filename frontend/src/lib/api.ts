import type { DatasetKind, DatasetPreviewResponse } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function uploadDataset(
  file: File,
  kind: DatasetKind
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