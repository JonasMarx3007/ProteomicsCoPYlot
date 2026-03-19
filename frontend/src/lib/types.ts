export type DatasetKind = "protein" | "phospho" | "peptide";
export type AnnotationKind = Extract<DatasetKind, "protein" | "phospho">;
export type FilterMode = "per_group" | "in_at_least_one_group";

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

export type ConditionAssignment = {
  name: string;
  columns: string[];
};

export type AnnotationFilterConfig = {
  minPresent: number;
  mode: FilterMode;
};

export type AnnotationGenerateRequest = {
  kind: AnnotationKind;
  conditions: ConditionAssignment[];
  isLog2Transformed: boolean;
  filter: AnnotationFilterConfig;
};

export type AnnotationResultResponse = {
  kind: AnnotationKind;
  sourceRows: number;
  sourceColumns: number;
  metadataRows: number;
  conditionCount: number;
  sampleCount: number;
  metadataPreview: Record<string, unknown>[];
  log2Rows: number;
  log2Columns: number;
  filteredRows: number;
  filteredColumns: number;
  filteredPreview: Record<string, unknown>[];
  isLog2Transformed: boolean;
  metadataSource: "manual" | "auto" | "uploaded";
  filter: AnnotationFilterConfig | null;
  autoDetected: boolean;
  warnings: string[];
};

export type MetadataUploadResponse = {
  kind: AnnotationKind;
  filename: string;
  rows: number;
  columns: number;
  createdAt: string;
  preview: Record<string, unknown>[];
};

export type DataSource = "filtered" | "log2" | "raw";

export type ImputationRunRequest = {
  kind: AnnotationKind;
  qValue: number;
  adjustStd: number;
  seed: number;
  sampleWise: boolean;
};

export type ImputationResultResponse = {
  kind: AnnotationKind;
  sourceUsed: DataSource;
  rows: number;
  columns: number;
  sampleColumns: string[];
  missingBefore: number;
  missingAfter: number;
  mean: number | null;
  std: number | null;
  quantile: number | null;
  qValue: number;
  adjustStd: number;
  seed: number;
  sampleWise: boolean;
  beforeMissingHistogram: ComparativeHistogramBin[];
  overallHistogram: HistogramBin[];
  normalFitCurve: CurvePoint[];
  afterImputationHistogram: ComparativeHistogramBin[];
  warnings: string[];
  preview: Record<string, unknown>[];
};

export type HistogramBin = {
  start: number;
  end: number;
  count: number;
};

export type ComparativeHistogramBin = {
  start: number;
  end: number;
  leftCount: number;
  rightCount: number;
};

export type CurvePoint = {
  x: number;
  y: number;
};

export type QQPoint = {
  theoretical: number;
  sample: number;
};

export type DistributionStats = {
  count: number;
  missingCount: number;
  min: number | null;
  max: number | null;
  mean: number | null;
  median: number | null;
  std: number | null;
};

export type DistributionSummaryResponse = {
  kind: AnnotationKind;
  sourceUsed: DataSource;
  sampleColumns: string[];
  stats: DistributionStats;
  rowsWithMissing: number;
  rowsWithoutMissing: number;
  qqPlot: QQPoint[];
  qqFitLine: CurvePoint[];
  warnings: string[];
};

export type FirstDigitPoint = {
  digit: number;
  observed: number;
  benford: number;
};

export type DuplicateFrequencyPoint = {
  occurrences: number;
  percentage: number;
};

export type VerificationSummaryResponse = {
  kind: AnnotationKind;
  sampleColumns: string[];
  firstDigit: FirstDigitPoint[];
  duplicateFrequency: DuplicateFrequencyPoint[];
  numericValueCount: number;
};

export type CompletenessTablesResponse = {
  kind: AnnotationKind;
  overallMissingPercent: number;
  outlierThreshold: number;
  outliers: string[];
  sampleSummary: Record<string, unknown>[];
  featureSummary: Record<string, unknown>[];
};

export type SampleMetricPoint = {
  sample: string;
  value: number;
};

export type BoxplotPoint = {
  sample: string;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
};

export type QcSummaryResponse = {
  kind: AnnotationKind;
  sourceUsed: DataSource;
  sampleColumns: string[];
  coverage: SampleMetricPoint[];
  intensityHistogram: HistogramBin[];
  boxplot: BoxplotPoint[];
  cv: SampleMetricPoint[];
  warnings: string[];
};

export type QcPlotOptionsResponse = {
  conditions: string[];
};

export type QcTableResponse = {
  rows: Record<string, unknown>[];
};

export type SidebarSection =
  | "data"
  | "completeness"
  | "qc"
  | "stats"
  | "peptide"
  | "singleProtein"
  | "phospho"
  | "comparison"
  | "summary"
  | "external";

export type DataTab =
  | "upload"
  | "annotation"
  | "imputation"
  | "distribution"
  | "verification";

export type QcTab =
  | "coverage"
  | "histogram"
  | "boxplot"
  | "cv"
  | "pca"
  | "abundance"
  | "correlation";

export type CompletenessTab = "missingPlot" | "heatmap" | "tables";
