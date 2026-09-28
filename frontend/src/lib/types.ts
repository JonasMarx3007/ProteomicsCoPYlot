export type DatasetKind = "protein" | "phospho" | "phosprot" | "peptide";
export type AnnotationKind = Extract<DatasetKind, "protein" | "phospho" | "phosprot">;
export type MetadataAnnotationKind = Extract<AnnotationKind, "protein" | "phospho">;
export type FilterMethod = "at_least_n" | "percentage";
export type FilterMode = "per_group" | "in_at_least_one_group" | "overall";

export type RRuntimeStatusResponse = {
  available: boolean;
  executable: string | null;
  version: string | null;
  versionOutput: string | null;
  detectedFrom: "env" | "path" | "common_path" | null;
  candidates: string[];
  error: string | null;
};

export type AdvancedTextElementSettings = {
  text?: string;
  size?: number;
  xOffset?: number;
  yOffset?: number;
  bold?: boolean;
  italic?: boolean;
  color?: string;
};

export type AdvancedPlotSettings = {
  titleElement?: AdvancedTextElementSettings;
  xLabelElement?: AdvancedTextElementSettings;
  yLabelElement?: AdvancedTextElementSettings;
  xTickLabelSize?: number;
  yTickLabelSize?: number;
  xTickLabelRotation?: number;
  yTickLabelRotation?: number;
  legendFontSize?: number;
  bold?: boolean;
  italic?: boolean;
  textXOffset?: number;
  textYOffset?: number;
  legendXOffset?: number;
  legendYOffset?: number;
  // The legend as an element rather than just a font size. `legendVisible` and
  // `legendFrame` are tri-state on the backend: absent leaves whatever the plot
  // itself chose.
  // Moved out of every page's options row, where "Toggle Header" appeared at 20
  // call sites under three different labels for one setting.
  titleVisible?: boolean;
  legendVisible?: boolean;
  legendTitle?: string;
  legendTextColor?: string;
  legendFrame?: boolean;
  xTickLabelColor?: string;
  yTickLabelColor?: string;
  referenceLineColor?: string;
  referenceLineVisible?: boolean;
  referenceLineStyle?: string;
  referenceLineWidth?: number;
  rowLabelSize?: number;
  rowLabelColor?: string;
  // The face every text in the figure is drawn in, and the five elements that
  // may disagree with it. An element left empty follows `fontFamily`; every
  // name here has to be a key of PLOT_FONTS in backend/app/services/plot_images.py.
  fontFamily?: string;
  titleFontFamily?: string;
  axisLabelFontFamily?: string;
  tickFontFamily?: string;
  legendFontFamily?: string;
  valueLabelFontFamily?: string;
  boxBorderColor?: string;
  boxMedianColor?: string;
  boxOutlierColor?: string;
  boxOutlierEdgeColor?: string;
  boxOutlierSize?: number;
  // Data points drawn over a box, which are a different class of dot from the
  // outlier fliers beside them and so get their own controls.
  boxPointSize?: number;
  boxPointAlpha?: number;
  boxPointEdgeColor?: string;
  boxPointEdgeWidth?: number;
  // The single-class plots: PCA, correlation, Q-Q, abundance, coverage
  // overlays, RT. Sizes are diameters in points, so one number means the same
  // dot whichever renderer draws it.
  markerSize?: number;
  markerAlpha?: number;
  markerEdgeColor?: string;
  markerEdgeWidth?: number;
  markerShape?: string;
  // Per-condition overrides. What is drawn is `this condition's value ?? the
  // general one ?? the plot's own default`, and choosing a general value clears
  // the map beside it, so every group snaps to it and can be pulled off again
  // one at a time.
  conditionMarkerSizes?: Record<string, number>;
  conditionMarkerShapes?: Record<string, string>;
  conditionMarkerAlphas?: Record<string, number>;
  conditionMarkerEdgeWidths?: Record<string, number>;
  conditionMarkerEdgeColors?: Record<string, string>;
  // The volcano has three classes of point in one figure and they are read
  // differently, so each is sized and faded on its own.
  volcanoUpSize?: number;
  volcanoUpAlpha?: number;
  volcanoUpColor?: string;
  volcanoDownSize?: number;
  volcanoDownAlpha?: number;
  volcanoDownColor?: string;
  volcanoNsSize?: number;
  volcanoNsAlpha?: number;
  volcanoNsColor?: string;
  volcanoHighlightSize?: number;
  volcanoHighlightColor?: string;
  volcanoLabelSize?: number;
  // Colours that used to be pickers in a plot's own options row.
  barColor?: string;
  classIColor?: string;
  classNotIColor?: string;
  vennColor1?: string;
  vennColor2?: string;
  vennColor3?: string;
  markerColor?: string;
  // The value labels drawn on bars and boxes. Was a per-page "Text Size",
  // clamped 6-20, 6-24 and 6-unbounded on the three pages that had it.
  valueLabelSize?: number;
  correlationColorMap?: string;
  backgroundColor?: string;
  transparentBackground?: boolean;
  plotTheme?: string;
  axisLineVisible?: boolean;
  axisLineColor?: string;
  axisLineWidth?: number;
  axisLineStyle?: string;
  axisLineTop?: boolean;
  axisLineRight?: boolean;
  axisLineBottom?: boolean;
  axisLineLeft?: boolean;
  gridLineVisible?: boolean;
  gridLineAxis?: string;
  gridLineColor?: string;
  gridLineWidth?: number;
  gridLineStyle?: string;
  conditionLabels?: Record<string, string>;
  sampleLabels?: Record<string, string>;
  conditionColors?: Record<string, string>;
};

export type DatasetPreviewResponse = {
  filename: string;
  kind: DatasetKind;
  format: string;
  rows: number;
  columns: number;
  columnNames: string[];
  preview: Record<string, unknown>[];
  suggestedIsLog2Transformed: boolean | null;
  sourcePath?: string | null;
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
  activePackage: string;
  availablePackages: string[];
  activeMetadataProfile: string;
  availableMetadataProfiles: string[];
  autoGeneratedMetadataProfiles: string[];
  protein: DatasetPreviewResponse | null;
  phospho: DatasetPreviewResponse | null;
  phosprot: DatasetPreviewResponse | null;
  peptide: PeptidePathResponse | null;
};

export type DatasetPackagesResponse = {
  activePackage: string;
  availablePackages: string[];
};

export type ConditionAssignment = {
  name: string;
  columns: string[];
};

export type SamplePairAssignment = {
  condition1Sample: string;
  condition2Sample: string;
};

export type PairingUpdateRequest = {
  kind: AnnotationKind;
  condition1: string;
  condition2: string;
  pairs: SamplePairAssignment[];
};

export type NormalizationMethod = "none" | "median" | "quantile" | "vsn";

/**
 * Which normalization methods this installation can run. VSN is delegated to
 * Bioconductor `vsn` via Rscript rather than reimplemented, so it is only
 * offered when R and the package are both present.
 */
export type NormalizationCapabilityResponse = {
  methods: NormalizationMethod[];
  vsnAvailable: boolean;
  vsnUnavailableReason: string | null;
  vsnPackageVersion: string | null;
};

export type AnnotationFilterConfig = {
  method: FilterMethod;
  minPresent: number;
  minPercentage: number;
  mode: FilterMode;
  /** Applied globally to the log2 values before filtering; never per condition. */
  normalization: NormalizationMethod;
};

export type AnnotationGenerateRequest = {
  kind: AnnotationKind;
  conditions: ConditionAssignment[];
  isLog2Transformed: boolean;
  filter: AnnotationFilterConfig;
};

export type Log2DetectionRequest = {
  kind: AnnotationKind;
  sampleColumns: string[];
};

/**
 * A JSON value. An object member may be `undefined`: an unset optional field,
 * which `JSON.stringify` leaves out, exactly as the request will carry it.
 */
export type ContextValue = string | number | boolean | null | ContextValue[] | { [key: string]: ContextValue | undefined };

/**
 * What the visible plot or panel shows: its data level, source, test and the
 * selections that determine its result. The page that owns the view builds it;
 * App keeps one per view and hands the active one to the assistant as
 * `view.mode`. The backend reads it through `ai_functions._mode_fields`.
 */
export type ContextMode = { [key: string]: ContextValue | undefined };

export type Log2DetectionResponse = {
  isLog2Transformed: boolean | null;
  sampleCount: number;
  reason: string;
};

export type AnnotationImputationInfo = {
  mode: string;
  applied: boolean;
  qValue: number | null;
  adjustStd: number | null;
  downShift: number | null;
  width: number | null;
  seed: number | null;
  sampleWise: boolean | null;
  sampleCount: number | null;
  rowCount: number | null;
  missingBefore: number | null;
  missingAfter: number | null;
};

export type PhosprotAggregationMode =
  | "robust_site_median"
  | "sum_propagate_na"
  | "sum_ignore_na"
  | "mean";

export type PhosprotAggregationSource = "non_imputed" | "imputed";

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
  log2AutoDetected: boolean;
  metadataSource: "manual" | "auto" | "uploaded" | "shared_phospho";
  filter: AnnotationFilterConfig | null;
  autoDetected: boolean;
  warnings: string[];
  imputation: AnnotationImputationInfo | null;
};

export type MetadataUploadResponse = {
  kind: MetadataAnnotationKind;
  profileName: string;
  profileNames: string[];
  autoGeneratedProfileCount: number;
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
  availableSamples: string[];
  availableProteins: string[];
  metadataLoaded: boolean;
  metadataFilename: string | null;
  warnings: string[];
};

export type PeptideQuantityOptionsResponse = {
  columns: string[];
  defaultColumn: string | null;
  requiresSelection: boolean;
};

export type PeptideSpecies = "human" | "mouse";

export type PeptideCoverageResponse = {
  protein: string;
  species: PeptideSpecies;
  coveragePercent: number;
  /** Peptides of the group that occur in the selected sequence (what the coverage is built from). */
  matchingPeptideCount: number;
  /** All peptides the report assigns to the protein group. */
  assignedPeptideCount: number;
  unmappedPeptides: string[];
  sequenceText: string;
  warnings: string[];
};

export type ResolvedSource = "data" | "filtered" | "log2" | "raw" | "imputed";
// What a panel may ask for. One name, one meaning, matching the backend.
export type DataSource = "data" | "filtered" | "imputed";

// What a selector offers and opens on. The backend decides both, so two pages
// cannot disagree about which matrices exist or which one is the default.
export interface DataSourceChoices {
  availableDataSources: DataSource[];
  defaultDataSource: DataSource;
}

export const NORMALIZATION_LABELS: Record<NormalizationMethod, string> = {
  none: "None",
  median: "Median centering",
  quantile: "Quantile normalization",
  vsn: "VSN",
};

export const DATA_SOURCE_LABELS: Record<DataSource, string> = {
  data: "Data",
  filtered: "Filtered Data",
  imputed: "Imputed Data",
};

// Options for a <SelectField>, in ladder order, limited to what exists.
export function dataSourceOptions(
  choices: Partial<DataSourceChoices> | null | undefined,
  selected?: DataSource
): { value: DataSource; label: string }[] {
  const available = choices?.availableDataSources?.length
    ? choices.availableDataSources
    : (["data"] as DataSource[]);
  const options = available.map((value) => ({ value, label: DATA_SOURCE_LABELS[value] }));
  if (selected && !available.includes(selected)) {
    options.push({ value: selected, label: `${DATA_SOURCE_LABELS[selected]} (unavailable)` });
  }
  return options;
}

// A restored choice, or null when there is none.
//
// The distinction is the whole point. Resolving a persisted value against no
// choices at all answers "data" when nothing was saved, and "data" is always available -- so
// the resolver that runs once the options arrive keeps it, and the served
// default becomes unreachable. Every selector opened on Data on projects whose
// backend was reporting `defaultDataSource: "imputed"` for exactly that reason.
export function savedDataSource(persisted: unknown): DataSource | null {
  const saved = String(persisted ?? "").trim();
  return saved in DATA_SOURCE_LABELS ? (saved as DataSource) : null;
}

// The most processed matrix that exists, unless a saved choice is still valid:
// restoring a panel must not quietly upgrade a deliberate selection.
export function resolveDataSource(
  persisted: unknown,
  choices: Partial<DataSourceChoices> | null | undefined
): DataSource {
  const available = choices?.availableDataSources ?? [];
  const saved = String(persisted ?? "").trim() as DataSource;
  if (available.includes(saved)) return saved;
  return choices?.defaultDataSource ?? "data";
}

export type ImputationRunRequest = {
  kind: AnnotationKind;
  method: "quantile" | "numerical";
  qValue: number;
  adjustStd: number;
  downShift: number;
  width: number;
  seed: number;
  sampleWise: boolean;
};

export type ImputationResultResponse = {
  kind: AnnotationKind;
  method: "quantile" | "numerical";
  sourceUsed: ResolvedSource;
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
  downShift: number;
  width: number;
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
  sourceUsed: ResolvedSource;
  sampleColumns: string[];
  stats: DistributionStats;
  rowsWithMissing: number;
  rowsWithoutMissing: number;
  qqPlot: QQPoint[];
  qqFitLine: CurvePoint[];
  warnings: string[];
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
  excludedAllMissingCount: number;
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

/**
 * Replicate CV for one condition, summarised across features. CV is computed
 * per feature across a condition's replicates on the linear intensity scale;
 * it is deliberately per-condition rather than per-sample, because a single
 * sample has no replicates to vary across.
 */
export type ConditionCvPoint = {
  condition: string;
  mean: number;
  median: number;
  q1: number;
  q3: number;
  lowerWhisker: number;
  upperWhisker: number;
};

export type QcSummaryResponse = {
  kind: AnnotationKind;
  sourceUsed: ResolvedSource;
  sampleColumns: string[];
  coverage: SampleMetricPoint[];
  intensityHistogram: HistogramBin[];
  boxplot: BoxplotPoint[];
  cv: ConditionCvPoint[];
  warnings: string[];
};

/**
 * How many features the PCA projection is actually built from. Dimensionality
 * reduction drops any feature with a missing value, so the projection can rest
 * on a small, abundance-biased subset; this makes that visible.
 */
export type QcPcaFeatureSummary = {
  featuresTotal: number;
  featuresComplete: number;
  featuresUsed: number;
  featuresRequired: number;
  /** Groups whose points do not span the plane, so no ellipse was drawn for
   * them. The figure never says so itself -- a plot taken out of the tool
   * should carry no caption about how the tool drew it -- so this notice is
   * the only place the omission is stated. */
  ellipseSkippedGroups: string[];
  /** Present when the cluster method is DBSCAN: the radius actually used,
   * as factor x median pairwise sample distance in the projection. */
  dbscan: { epsFactor: number; medianSampleDistance: number; epsEffective: number } | null;
};

export type QcPlotOptionsResponse = {
  conditions: string[];
  imputedAvailable: boolean;
  samples?: string[];
  sampleLabels?: Record<string, string>;
  sampleLabelsWithId?: Record<string, string>;
  availableDataSources: DataSource[];
  defaultDataSource: DataSource;
  /** True only for a phosphoprotein dataset collapsed with `robust_site_median`,
   * whose stored values are ratios to each site's own median rather than
   * abundances. */
  centredPhosprotValues: boolean;
};

export type PeptideMetadataGenerateRequest = {
  conditions: ConditionAssignment[];
};

export type QcTableResponse = {
  rows: Record<string, unknown>[];
};

export type StatsIdentifier = "workflow" | "genes";
/**
 * Independent samples: pooled Student's t or unequal-variance Welch.
 * Paired samples: a t-test on matched within-pair differences.
 */
export type StatsTestType =
  | "unpaired"
  | "unpaired_welch"
  | "paired";
export type SimulationTestType = "unpaired" | "unpaired_welch";
export type AnovaSource = "anova" | "anova_cluster";
export type AnovaPostHoc = "none" | "tukey";
// Mirrors AnovaClusterMethod in backend/app/schemas/stats.py; the union and the
// selector options are held to it by tests/repository/test_frontend_backend_enums.py.
export type AnovaClusterMethod =
  | "average"
  | "ward"
  | "complete"
  | "weighted"
  | "single";
export type StatsTab =
  | "volcano"
  | "anova"
  | "ora"
  | "pathwayHeatmap"
  | "simulation";

export type PeptideTab =
  | "rtPlot"
  | "modification"
  | "missedCleavage"
  | "sequenceCoverage";

export type StatisticalOptionsResponse = {
  kind: AnnotationKind;
  sourceUsed: ResolvedSource;
  imputedAvailable: boolean;
  availableConditions: string[];
  samplesByCondition: Record<string, string[]>;
  pairIdsBySample: Record<string, string>;
  availableIdentifiers: { key: StatsIdentifier; label: string }[];
  warnings: string[];
  availableDataSources: DataSource[];
  defaultDataSource: DataSource;
};

export type VolcanoRequest = {
  kind: AnnotationKind;
  dataSource: DataSource;
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
  sourceUsed: ResolvedSource;
  labelColumn: string;
  totalRows: number;
  upregulatedCount: number;
  downregulatedCount: number;
  notSignificantCount: number;
  rows: Record<string, unknown>[];
  warnings: string[];
};

/** Which Gene Ontology database the query is matched against. One entry today;
 * a second organism is a member here and a table on the backend, not a new code
 * path. The backend refuses a key it has no database for rather than falling
 * back to human. */
export type EnrichmentOrganism = "human";

export const ENRICHMENT_ORGANISM_OPTIONS: { value: EnrichmentOrganism; label: string }[] = [
  { value: "human", label: "Human (Homo sapiens)" },
];

export type EnrichmentRequest = {
  kind: AnnotationKind;
  source: "volcano" | "volcano_control" | "anova";
  dataSource: DataSource;
  condition1: string;
  condition2: string;
  condition1Control?: string | null;
  condition2Control?: string | null;
  pValueThreshold: number;
  log2fcThreshold: number;
  testType: StatsTestType;
  useUncorrected: boolean;
  selectedCluster?: number | null;
  nClusters: number;
  clusterMethod: AnovaClusterMethod;
  adjPValueCutoff: number;
  topN: number;
  minTermSize: number;
  maxTermSize: number;
  backgroundMode: "experiment" | "global";
  organism: EnrichmentOrganism;
};

export type EnrichmentTerm = {
  source: string;
  termId: string;
  name: string;
  termSize: number;
  intersectionSize: number;
  querySize: number;
  geneRatio: number;
  hitPercent: number;
  pValue: number;
  adjPValue: number;
  intersectingGenes: string[];
};

export type EnrichmentResultResponse = {
  kind: AnnotationKind;
  sourceUsed: ResolvedSource;
  selectedCluster: number | null;
  clusterGenes: string[];
  clusterTerms: EnrichmentTerm[];
  upGenes: string[];
  downGenes: string[];
  upTerms: EnrichmentTerm[];
  downTerms: EnrichmentTerm[];
  backgroundMode: "experiment" | "global";
  backgroundGenes: string[];
  backgroundSize: number;
  annotatedBackgroundSize: number;
  organism: string;
  correctionMethod: string;
  upstreamCorrectionMethod: string;
  databaseSha256: string;
  testedTermCount: number;
  termCounts: Record<string, { searchSpace: number; overlapTested: number; passingCutoff: number; displayed: number }>;
  warnings: string[];
};

export type ListEnrichmentRequest = {
  genes: string[];
  backgroundMode: "experiment" | "global";
  backgroundGenes: string[];
  topN: number;
  minTermSize: number;
  maxTermSize: number;
  adjPValueCutoff: number;
  organism: EnrichmentOrganism;
};

export type ListEnrichmentResultResponse = {
  evidenceToken?: string;
  genes: string[];
  terms: EnrichmentTerm[];
  backgroundMode: "experiment" | "global";
  backgroundGenes: string[];
  backgroundSize: number;
  annotatedBackgroundSize: number;
  organism: string;
  correctionMethod: string;
  databaseSha256: string;
  testedTermCount: number;
  termCounts: Record<string, { searchSpace: number; overlapTested: number; passingCutoff: number; displayed: number }>;
  warnings: string[];
};

export type PathwayOptionsResponse = {
  pathways: string[];
};

export type SimulationRequest = {
  kind: AnnotationKind;
  source: "volcano";
  dataSource: DataSource;
  condition1: string;
  condition2: string;
  identifier: StatsIdentifier;
  pValueThreshold: number;
  log2fcThreshold: number;
  testType: SimulationTestType;
  useUncorrected: boolean;
  varianceMultiplier: number;
  sampleSizeOverride: number;
};

export type SimulationResultResponse = {
  kind: AnnotationKind;
  sourceUsed: ResolvedSource;
  testType: SimulationTestType;
  condition1: string;
  condition2: string;
  sampleSizeMode: "observed" | "override";
  sampleSizeOverride: number;
  effectiveSampleSizeCondition1Min: number;
  effectiveSampleSizeCondition1Max: number;
  effectiveSampleSizeCondition2Min: number;
  effectiveSampleSizeCondition2Max: number;
  labelColumn: string;
  totalRows: number;
  upregulatedCount: number;
  downregulatedCount: number;
  notSignificantCount: number;
  rows?: Record<string, unknown>[];
  warnings: string[];
};

export type AnalysisSource = "volcano" | "volcano_control";

export type AnalysisVolcanoRequest = {
  dataSource?: DataSource;
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
  selectionKey?: string | null;
  boxplotLabel?: string | null;
  boxplotIdentifier?: StatsIdentifier | null;
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
  dataSource: DataSource;
  availableDataSources: DataSource[];
  defaultDataSource: DataSource;
};

export type SingleProteinIdentifier = "workflow" | "genes";
// One vocabulary for every pipeline. "auto" takes the first available of
// filtered, log2, raw; "log2" is the complete matrix before filtering. "data"
// is the historical spelling, still accepted by the API, where it resolves to
// each path's own default -- send a canonical value instead.

export type SingleProteinTableResponse = {
  rows: Record<string, unknown>[];
};

export type PhosphoOptionsResponse = {
  conditions: string[];
  samplesByCondition: Record<string, string[]>;
  pairIdsBySample: Record<string, string>;
  features: string[];
  imputedAvailable: boolean;
  availableDataSources: DataSource[];
  defaultDataSource: DataSource;
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
  dataSource: DataSource;
  filteredAvailable: boolean;
  imputedAvailable: boolean;
};

export type ComparisonTableResponse = {
  rows: Record<string, unknown>[];
};

export type ExternalTab = "peptideCollapse" | "gonetView";

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

export type SummarySectionNote = {
  above: string;
  below: string;
};

export type PeptideCollapseRequest = {
  inputPath: string;
  outputPath: string | null;
  cutoff: number;
};

export type PeptideCollapseResponse = {
  success: boolean;
  inputPath: string;
  outputPath: string | null;
  cutoff: number;
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

// Which renderer draws a volcano. The same two words the QC plots use, so one
// vocabulary covers every plot that has both.
export type VolcanoRenderType = "Normal" | "Interactive";

export const VOLCANO_RENDER_TYPE_OPTIONS: { value: VolcanoRenderType; label: string }[] = [
  { value: "Interactive", label: "Interactive" },
  { value: "Normal", label: "Normal" },
];

export function restoreVolcanoRenderType(value: unknown): VolcanoRenderType {
  return String(value ?? "").trim() === "Normal" ? "Normal" : "Interactive";
}

export type SummaryVolcanoEntry = {
  kind: AnnotationKind;
  control: boolean;
  dataSource: DataSource;
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
  // Captured when the entry is added, so the report renders each comparison the
  // way it was being looked at.
  renderType?: VolcanoRenderType;
  labelTopUp?: number;
  labelTopDown?: number;
};

export type SummaryReportContext = {
  completenessSettings?: Record<string, unknown>;
  qcSettings?: Record<string, Record<string, unknown>>;
  volcanoEntries?: SummaryVolcanoEntry[];
  advancedPlotMode?: boolean;
  advancedPlotSettingsByKey?: Record<string, AdvancedPlotSettings>;
  qcAdvancedSettingsByTab?: Record<string, AdvancedPlotSettings>;
  completenessAdvancedSettingsByTab?: Record<string, AdvancedPlotSettings>;
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
  | "external"
  | "settings";

export type DataTab =
  | "upload"
  | "annotation"
  | "imputation"
  | "distribution"
  | "translator"
  | "conditionPalette"
  | "restore";

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

export type ChatRole = "system" | "user" | "assistant";
export type ChatProvider = "ollama" | "openai" | "anthropic" | "gemini";
export type ModelContextTier = "compact" | "standard" | "extended";

export type ChatMessage = {
  role: ChatRole;
  content: string;
};

export type CloudAiConsentStatus = {
  provider: ChatProvider;
  providerLabel: string;
  required: boolean;
  granted: boolean;
  disclosureVersion: string;
  transmitted: string[];
  excluded: string[];
  notice: string;
};

export type OllamaGpuStatusResponse = {
  gpuEligible: boolean;
  gpuEnabledDefault: boolean;
  provider: string | null;
  deviceName: string | null;
  reason: string | null;
  remoteEndpoint?: boolean;
  acceleration?: "gpu" | "cpu" | "unknown";
};

export type OllamaModelsResponse = {
  models: string[];
  selectedModel: string | null;
  warnings: string[];
};

export type ModelCapabilityResponse = {
  assessment: "tested" | "inferred" | "unknown";
  provider: ChatProvider;
  model: string;
  level: 1 | 2 | 3;
  label: "Low" | "Medium" | "High";
  contextTier: ModelContextTier;
  contextWindow: number | null;
  parameterCountB: number | null;
  supportsTools: boolean | null;
  supportsVision: boolean | null;
  source: "metadata" | "model_name" | "configured" | "fallback";
  reason: string;
};

export type AnovaRequest = {
  kind: AnnotationKind;
  source: AnovaSource;
  dataSource: DataSource;
  identifier: StatsIdentifier;
  pValueThreshold: number;
  useUncorrected: boolean;
  showDendrograms: boolean;
  showLegend: boolean;
  nClusters: number;
  clusterMethod: AnovaClusterMethod;
  postHoc: AnovaPostHoc;
  // Which pair the post-hoc reports. Tukey's q still uses every condition -- k
  // and the pooled MSE come from the whole design -- so restricting the
  // comparison changes what comes back, never what a returned number means.
  // Both absent means every pair.
  postHocCondition1?: string;
  postHocCondition2?: string;
};

export type AnovaResultResponse = {
  kind: AnnotationKind;
  source: AnovaSource;
  sourceUsed: ResolvedSource;
  labelColumn: string;
  totalRows: number;
  significantCount: number;
  clusterCount: number | null;
  completenessNotice: string | null;
  rows: Record<string, unknown>[];
  clusterRows: Record<string, unknown>[];
  postHocMethod: string | null;
  postHocRows: Record<string, unknown>[];
  postHocSignificantCount: number;
  // The pair actually compared, echoed so the table can say so; null when every
  // pair was computed.
  postHocComparison: string | null;
  warnings: string[];
};

export type OllamaModelManageResponse = {
  ok: boolean;
  action: "install" | "remove";
  model: string;
  detail: string;
  models: string[];
  selectedModel: string | null;
  warnings: string[];
};

export type ViewerAuthStatusResponse = {
  enabled: boolean;
  authenticated: boolean;
  project: string | null;
  projectLabel: string | null;
};

export type ViewerAuthLoginResponse = {
  ok: boolean;
  project: string;
  projectLabel: string;
};

export type ToolAuthStatusResponse = {
  enabled: boolean;
  authenticated: boolean;
};

export type ToolAuthLoginResponse = {
  ok: boolean;
};

export type RestoreDatasetKind = "protein" | "phospho" | "phosprot" | "peptide";

export type RestoreMissingFile = {
  packageName: string;
  kind: RestoreDatasetKind;
  filename?: string | null;
  expectedPath?: string | null;
  message: string;
};

export type RestoreImportResponse = {
  ok: boolean;
  uiState: Record<string, unknown>;
  warnings: string[];
  missingFiles: RestoreMissingFile[];
  restoredDatasets: string[];
  restoredAnnotations: string[];
};
