export type DatasetKind = "protein" | "phospho";

export type DatasetPreviewResponse = {
  datasetId: string;
  filename: string;
  kind: DatasetKind;
  format: string;
  rows: number;
  columns: number;
  columnNames: string[];
  preview: Record<string, unknown>[];
};

export type SidebarSection =
  | "data"
  | "qc"
  | "stats"
  | "peptide"
  | "singleProtein"
  | "phospho"
  | "comparison"
  | "summary"
  | "external";

export type DataTab = "upload" | "meta";