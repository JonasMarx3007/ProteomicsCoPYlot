export type DatasetKind = "protein" | "phospho" | "peptide";

export type DatasetPreviewResponse = {
  filename: string;
  kind: DatasetKind;
  format: string;
  rows: number;
  columns: number;
  columnNames: string[];
  preview: Record<string, unknown>[];
};

export type PeptidePathResponse = {
  filename: string;
  kind: "peptide";
  format: string;
  path: string;
  rows: number;
  columns: number;
  columnNames: string[];
  preview: Record<string, unknown>[];
};

export type CurrentDatasetsResponse = {
  protein: DatasetPreviewResponse | null;
  phospho: DatasetPreviewResponse | null;
  peptide: PeptidePathResponse | null;
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