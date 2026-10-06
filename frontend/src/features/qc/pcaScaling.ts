/**
 * The PCA/UMAP/t-SNE feature-scaling selector: what it offers and what each
 * method starts on. Tested in tests/component/pca-scaling.test.ts.
 */

export function pcaMethodLabel(method: string): string {
  const key = String(method || "").trim().toLowerCase();
  if (key === "umap") return "UMAP";
  if (key === "t-sne" || key === "tsne" || key === "t_sne") return "t-SNE";
  return "PCA";
}

// Two scalings exist and they answer different questions, so both are named:
// centred weights a feature by its variance, unit variance gives every feature
// equal weight. `auto` is still what the API takes and what older saved states
// hold, but it is never shown -- for PCA it *is* centred and for UMAP/t-SNE it
// *is* unit variance, so offering it put the same scaling in the list twice
// under two names.
export const SCALING_LABELS = ["Centred", "Unit variance"] as const;

export function methodDefaultScaling(method: string): string {
  return pcaMethodLabel(method) === "PCA" ? "centered" : "unit_variance";
}

export function scalingLabel(scaling: string, method: string): string {
  const key = String(scaling || "auto").trim().toLowerCase();
  if (key === "centered" || key === "centred") return "Centred";
  if (key === "unit_variance" || key === "scaled") return "Unit variance";
  return scalingLabel(methodDefaultScaling(method), method);
}

export function scalingValue(label: string): string {
  return label === "Unit variance" ? "unit_variance" : "centered";
}
