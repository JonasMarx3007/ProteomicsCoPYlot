// The tabs of each sidebar section, in the order they are shown. Kept out of
// App.tsx so the set of views can be checked against the assistant's plot
// catalogue (tests/unit/assistant-plot-catalogue.test.ts).
import type {
  ComparisonTab,
  CompletenessTab,
  DataTab,
  ExternalTab,
  PeptideTab,
  PhosphoTab,
  QcTab,
  SingleProteinTab,
  StatsTab,
  SummaryTab,
} from "./types";

export const dataTabs: { key: DataTab; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "annotation", label: "Annotation" },
  { key: "imputation", label: "Imputation" },
  { key: "distribution", label: "Distribution" },
  { key: "translator", label: "ID Translator" },
  { key: "conditionPalette", label: "Colors" },
  { key: "restore", label: "Restore" },
];

export const qcTabs: { key: QcTab; label: string }[] = [
  { key: "coverage", label: "Coverage Plot" },
  { key: "histogram", label: "Histogram Intensity" },
  { key: "boxplot", label: "Boxplot Intensity" },
  { key: "cv", label: "CV Plot" },
  { key: "pca", label: "Principal Component Analysis" },
  { key: "abundance", label: "Abundance Plot" },
  { key: "correlation", label: "Correlation Plot" },
];

export const completenessTabs: { key: CompletenessTab; label: string }[] = [
  { key: "missingPlot", label: "Missing Value Plot" },
  { key: "heatmap", label: "Missing Value Heatmap" },
  { key: "tables", label: "Tables" },
];

export const statsTabs: { key: StatsTab; label: string }[] = [
  { key: "volcano", label: "Volcano Plot" },
  { key: "anova", label: "One-way ANOVA" },
  { key: "ora", label: "GO Enrichment (ORA)" },
  { key: "pathwayHeatmap", label: "Pathway Heatmap" },
  { key: "simulation", label: "Replicate & Variance Projection" },
];

export const peptideTabs: { key: PeptideTab; label: string }[] = [
  { key: "rtPlot", label: "RT Plot" },
  { key: "modification", label: "Modification Plot" },
  { key: "missedCleavage", label: "Missed Cleavage Plot" },
  { key: "sequenceCoverage", label: "Sequence Coverage" },
];

export const singleProteinTabs: { key: SingleProteinTab; label: string }[] = [
  { key: "boxplot", label: "Protein Boxplot" },
  { key: "lineplot", label: "Protein Lineplot" },
  { key: "heatmap", label: "Phosphosites on Protein Heatmap" },
];

export const phosphoTabs: { key: PhosphoTab; label: string }[] = [
  { key: "phosphositePlot", label: "Phosphosite Plot" },
  { key: "coverage", label: "Phosphosite Coverage Plot" },
  { key: "ksea", label: "Kinase Library" },
  { key: "distribution", label: "Phosphosite Distribution" },
  { key: "sty", label: "STY Plot" },
  { key: "phosprotRegulation", label: "Phosphoprotein Regulation" },
];

export const comparisonTabs: { key: ComparisonTab; label: string }[] = [
  { key: "pearson", label: "Pearson Correlation" },
  { key: "venn", label: "Venn Diagram" },
];

export const externalTabs: { key: ExternalTab; label: string }[] = [
  { key: "peptideCollapse", label: "Peptide Collapse" },
  { key: "gonetView", label: "GONetView" },
];

export const summaryTabs: { key: SummaryTab; label: string }[] = [
  { key: "tables", label: "Tables" },
  { key: "text", label: "Text" },
  { key: "report", label: "Report" },
];

export const viewerDataTabs: { key: DataTab; label: string }[] = dataTabs.filter(
  (tab) => tab.key === "upload" || tab.key === "annotation"
);
