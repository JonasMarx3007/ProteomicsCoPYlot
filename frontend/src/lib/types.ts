export type DatasetKind = "protein" | "phospho" | "phosprot" | "peptide";
export type AnnotationKind = Extract<DatasetKind, "protein" | "phospho" | "phosprot">;
export type MetadataAnnotationKind = Extract<AnnotationKind, "protein" | "phospho">;
export type FilterMode = "per_group" | "in_at_least_one_group";

export type DatasetPreviewResponse = {
  filename: string;
  kind: DatasetKind;
  format: string;
  rows: number;
  columns: number;
  columnNames: string[];
  preview: Record<string, unknown>[];
  suggestedIsLog2Transformed: boolean;
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
  phosprot: DatasetPreviewResponse | null;
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

export type PhosprotAggregationMode =
  | "sum_mean_impute"
  | "sum_propagate_na"
  | "sum_ignore_na"
  | "mean";

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
  metadataSource: "manual" | "auto" | "uploaded" | "shared_phospho";
  filter: AnnotationFilterConfig | null;
  autoDetected: boolean;
  warnings: string[];
};

export type MetadataUploadResponse = {
  kind: MetadataAnnotationKind;
  filename: string;
  rows: number;
  columns: number;
  createdAt: string;
  preview: Record<string, unknown>[];
};

export type PeptideMetadataResponse = {
  filename: string;
  rows: number;
  columns: number;
  createdAt: string;
  preview: Record<string, unknown>[];
};

export type PeptideOverviewResponse = {
  filename: string;
  path: string;
  rows: number;
  columns: number;
  columnNames: string[];
  availableProteins: string[];
  metadataLoaded: boolean;
  metadataFilename: string | null;
  warnings: string[];
};

export type PeptideSpecies = "human" | "mouse";

export type PeptideCoverageResponse = {
  protein: string;
  species: PeptideSpecies;
  coveragePercent: number;
  matchingPeptideCount: number;
  sequenceText: string;
  warnings: string[];
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

export type IdTranslationRequest = {
  kind: AnnotationKind;
  column: string;
  inputDb: string | null;
  outputDb: string;
  autoDetectInput: boolean;
};

export type IdTranslationResponse = {
  kind: AnnotationKind;
  sourceColumn: string;
  outputColumn: string;
  inputDb: string;
  outputDb: string;
  translatedCount: number;
  totalRows: number;
  preview: Record<string, unknown>[];
  availableColumns: string[];
  availableDatabases: string[];
  downloadFilename: string;
  warnings: string[];
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

export type StatsIdentifier = "workflow" | "genes";
export type StatsTestType = "unpaired" | "paired";
export type StatsTab =
  | "volcano"
  | "volcanoControl"
  | "gsea"
  | "pathwayHeatmap"
  | "simulation";

export type PeptideTab =
  | "rtPlot"
  | "modification"
  | "missedCleavage"
  | "sequenceCoverage";

export type StatisticalOptionsResponse = {
  kind: AnnotationKind;
  sourceUsed: DataSource;
  availableConditions: string[];
  availableIdentifiers: { key: StatsIdentifier; label: string }[];
  warnings: string[];
};

export type VolcanoRequest = {
  kind: AnnotationKind;
  condition1: string;
  condition2: string;
  identifier: StatsIdentifier;
  pValueThreshold: number;
  log2fcThreshold: number;
  testType: StatsTestType;
  useUncorrected: boolean;
  highlightTerms: string[];
};

export type VolcanoControlRequest = VolcanoRequest & {
  condition1Control: string;
  condition2Control: string;
};

export type VolcanoResultResponse = {
  kind: AnnotationKind;
  sourceUsed: DataSource;
  labelColumn: string;
  totalRows: number;
  upregulatedCount: number;
  downregulatedCount: number;
  notSignificantCount: number;
  rows: Record<string, unknown>[];
  warnings: string[];
};

export type EnrichmentRequest = {
  kind: AnnotationKind;
  source: "volcano" | "volcano_control";
  condition1: string;
  condition2: string;
  condition1Control?: string | null;
  condition2Control?: string | null;
  pValueThreshold: number;
  log2fcThreshold: number;
  testType: StatsTestType;
  useUncorrected: boolean;
  topN: number;
  minTermSize: number;
  maxTermSize: number;
};

export type EnrichmentTerm = {
  source: string;
  termId: string;
  name: string;
  termSize: number;
  intersectionSize: number;
  hitPercent: number;
  pValue: number;
  adjPValue: number;
  intersectingGenes: string[];
};

export type EnrichmentResultResponse = {
  kind: AnnotationKind;
  sourceUsed: DataSource;
  upGenes: string[];
  downGenes: string[];
  upTerms: EnrichmentTerm[];
  downTerms: EnrichmentTerm[];
  warnings: string[];
};

export type ListEnrichmentRequest = {
  genes: string[];
  topN: number;
  minTermSize: number;
  maxTermSize: number;
};

export type ListEnrichmentResultResponse = {
  genes: string[];
  terms: EnrichmentTerm[];
  warnings: string[];
};

export type PathwayOptionsResponse = {
  pathways: string[];
};

export type SimulationRequest = {
  kind: AnnotationKind;
  condition1: string;
  condition2: string;
  pValueThreshold: number;
  log2fcThreshold: number;
  varianceMultiplier: number;
  sampleSizeOverride: number;
};

export type SimulationResultResponse = {
  kind: AnnotationKind;
  sourceUsed: DataSource;
  totalRows: number;
  upregulatedCount: number;
  downregulatedCount: number;
  notSignificantCount: number;
  warnings: string[];
};

export type AnalysisSource = "volcano" | "volcano_control";

export type AnalysisVolcanoRequest = {
  kind: AnnotationKind;
  source: AnalysisSource;
  condition1: string;
  condition2: string;
  condition1Control?: string | null;
  condition2Control?: string | null;
  identifier: StatsIdentifier;
  pValueThreshold: number;
  log2fcThreshold: number;
  testType: StatsTestType;
  useUncorrected: boolean;
};

export type AnalysisVolcanoPoint = {
  label: string;
  selectionLabel: string;
  uniprotAccession?: string | null;
  workflowLabel?: string | null;
  geneLabel?: string | null;
  significance: string;
  log2FC: number;
  negLog10P: number;
};

export type AnalysisVolcanoResponse = {
  kind: AnnotationKind;
  source: AnalysisSource;
  labelColumn: string;
  totalRows: number;
  upregulatedCount: number;
  downregulatedCount: number;
  notSignificantCount: number;
  points: AnalysisVolcanoPoint[];
  warnings: string[];
};

export type SingleProteinOptionsResponse = {
  proteins: string[];
  conditions: string[];
  proteinCount: number;
  conditionCount: number;
  identifier: SingleProteinIdentifier;
  availableIdentifiers: { key: SingleProteinIdentifier; label: string }[];
};

export type SingleProteinIdentifier = "workflow" | "genes";

export type SingleProteinTableResponse = {
  rows: Record<string, unknown>[];
};

export type PhosphoOptionsResponse = {
  conditions: string[];
  features: string[];
};

export type PhosphoTableResponse = {
  rows: Record<string, unknown>[];
};

export type ComparisonTab = "pearson" | "venn";

export type ComparisonOptionsResponse = {
  samples: string[];
  conditions: string[];
  sampleCount: number;
  conditionCount: number;
};

export type ComparisonTableResponse = {
  rows: Record<string, unknown>[];
};

export type ExternalTab = "peptideCollapse";

export type SummaryTableBlock = {
  key: string;
  title: string;
  rows: Record<string, unknown>[];
  rowCount: number;
  available: boolean;
  message: string | null;
};

export type SummarySectionInfo = {
  key: string;
  title: string;
  group: string;
  description: string;
};

export type SummaryOverviewResponse = {
  tables: SummaryTableBlock[];
  availableSections: SummarySectionInfo[];
  warnings: string[];
  suggestedFilename: string;
};

export type SummarySectionNote = {
  above: string;
  below: string;
};

export type SummaryLegacyReportRequest = {
  title: string;
  author: string;
  introduction: string;
  notes: Record<string, SummarySectionNote>;
  includeMetadataTables: boolean;
};

export type PeptideCollapseRequest = {
  inputPath: string;
  outputPath: string | null;
  cutoff: number;
  collapseVersion: "newest" | "legacy";
};

export type PeptideCollapseResponse = {
  success: boolean;
  inputPath: string;
  outputPath: string | null;
  cutoff: number;
  collapseVersion: "newest" | "legacy";
  rows: number | null;
  columns: number | null;
  columnNames: string[];
  preview: Record<string, unknown>[];
  logs: string;
  error: string | null;
};

export type SummaryMetadataTable = {
  kind: AnnotationKind;
  available: boolean;
  rows: number;
  columns: number;
  columnNames: string[];
  table: Record<string, unknown>[];
};

export type SummaryTablesResponse = {
  protein: SummaryMetadataTable;
  phospho: SummaryMetadataTable;
};

export type SummaryReportRequest = {
  title: string;
  author: string;
  textEntries: Record<string, string>;
  reportContext?: SummaryReportContext;
};

export type SummaryReportResponse = {
  fileName: string;
  html: string;
  warnings: string[];
};

export type ConditionPaletteResponse = {
  kind: AnnotationKind;
  palette: Record<string, string>;
};

export type SummaryVolcanoEntry = {
  kind: AnnotationKind;
  control: boolean;
  condition1: string;
  condition2: string;
  condition1Control?: string | null;
  condition2Control?: string | null;
  identifier: StatsIdentifier;
  pValueThreshold: number;
  log2fcThreshold: number;
  testType: StatsTestType;
  useUncorrected: boolean;
  highlightTerms: string[];
};

export type SummaryReportContext = {
  qcSettings?: Record<string, Record<string, unknown>>;
  volcanoEntries?: SummaryVolcanoEntry[];
};

export type SummaryTab = "tables" | "text" | "report";

export type SidebarSection =
  | "data"
  | "analysis"
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
  | "verification"
  | "translator"
  | "conditionPalette";

export type QcTab =
  | "coverage"
  | "histogram"
  | "boxplot"
  | "cv"
  | "pca"
  | "abundance"
  | "correlation";

export type CompletenessTab = "missingPlot" | "heatmap" | "tables";
export type SingleProteinTab = "boxplot" | "lineplot" | "heatmap";
export type PhosphoTab =
  | "phosphositePlot"
  | "coverage"
  | "ksea"
  | "distribution"
  | "sty"
  | "phosprotRegulation";
