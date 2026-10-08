import type { components } from "./generated/api";

type Schemas = components["schemas"];
/** A response as the backend sends it. The generated types mark every field with a
 * default as optional (right for requests); pydantic serializes those fields too, so
 * in a response none is ever absent. */
type Served<T> = T extends readonly (infer U)[] ? Served<U>[] : T extends object ? { [K in keyof T]-?: Served<T[K]> } : T;

export type DatasetKind = "protein" | "phospho" | "phosprot" | "peptide";
export type AnnotationKind = Extract<DatasetKind, "protein" | "phospho" | "phosprot">;
export type MetadataAnnotationKind = Extract<AnnotationKind, "protein" | "phospho">;
export type FilterMethod = "at_least_n" | "percentage";
export type FilterMode = "per_group" | "in_at_least_one_group" | "overall";

export type RRuntimeStatusResponse = Served<Schemas["RRuntimeStatusResponse"]>;

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

export type DatasetPreviewResponse = Served<Schemas["DatasetPreviewResponse"]>;

export type PeptidePathResponse = Served<Schemas["PeptidePathResponse"]>;

export type CurrentDatasetsResponse = Served<Schemas["CurrentDatasetsResponse"]>;

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
export type NormalizationCapabilityResponse = Served<Schemas["NormalizationCapabilityResponse"]>;

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

export type Log2DetectionResponse = Served<Schemas["Log2DetectionResponse"]>;

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

export type AnnotationResultResponse = Served<Schemas["AnnotationResultResponse"]>;

export type MetadataUploadResponse = Served<Schemas["MetadataUploadResponse"]>;

export type PeptideMetadataResponse = Served<Schemas["PeptideMetadataResponse"]>;

export type PeptideOverviewResponse = Served<Schemas["PeptideOverviewResponse"]>;

export type PeptideQuantityOptionsResponse = Served<Schemas["PeptideQuantityOptionsResponse"]>;

export type PeptideSpecies = "human" | "mouse";

export type PeptideCoverageResponse = Served<Schemas["PeptideCoverageResponse"]>;

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

/** The normalizations the annotation page offers; VSN only where R can run it. */
export function normalizationOptions(vsnAvailable: boolean): NormalizationMethod[] {
  return vsnAvailable ? ["none", "median", "quantile", "vsn"] : ["none", "median", "quantile"];
}

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

export type ImputationResultResponse = Served<Schemas["ImputationResultResponse"]>;

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

export type DistributionSummaryResponse = Served<Schemas["DistributionSummaryResponse"]>;

export type IdTranslationRequest = {
  kind: AnnotationKind;
  column: string;
  inputDb: string | null;
  outputDb: string;
  autoDetectInput: boolean;
};

export type IdTranslationResponse = Served<Schemas["IdTranslationResponse"]>;

export type CompletenessTablesResponse = Served<Schemas["CompletenessTablesResponse"]>;

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
  /** Set when UMAP or t-SNE settings exceed what the number of samples supports. */
  smallSampleNotice?: string | null;
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
// selector options are held to it by tests/contracts/test_frontend_backend_enums.py.
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

export type StatisticalOptionsResponse = Served<Schemas["StatisticalOptionsResponse"]>;

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

export type VolcanoResultResponse = Served<Schemas["VolcanoResultResponse"]>;

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

export type EnrichmentResultResponse = Served<Schemas["EnrichmentResultResponse"]>;

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

export type ListEnrichmentResultResponse = Served<Schemas["ListEnrichmentResultResponse"]>;

export type PathwayOptionsResponse = Served<Schemas["PathwayOptionsResponse"]>;

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

export type SimulationResultResponse = Served<Schemas["SimulationResultResponse"]>;

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

export type AnalysisVolcanoResponse = Served<Schemas["AnalysisVolcanoResponse"]>;

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
  notebookToken?: string | null;
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

export type SummaryMetadataTable = {
  kind: AnnotationKind;
  available: boolean;
  rows: number;
  columns: number;
  columnNames: string[];
  table: Record<string, unknown>[];
};

export type SummaryTablesResponse = Served<Schemas["SummaryTablesResponse"]>;

export type SummaryReportRequest = {
  title: string;
  author: string;
  textEntries: Record<string, string>;
  reportContext?: SummaryReportContext;
};

export type SummaryReportResponse = Served<Schemas["SummaryReportResponse"]>;

export type ConditionPaletteResponse = Served<Schemas["ConditionPaletteResponse"]>;

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
export type ChatProvider = "ollama" | "openai_compatible" | "openai" | "anthropic" | "gemini";
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

export type OllamaGpuStatusResponse = Served<Schemas["OllamaGpuStatusResponse"]>;

export type OllamaModelsResponse = Served<Schemas["OllamaModelsResponse"]>;

export type ModelCapabilityResponse = Served<Schemas["ModelCapabilityResponse"]>;

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

export type AnovaResultResponse = Served<Schemas["AnovaResultResponse"]>;

export type OllamaModelManageResponse = Served<Schemas["OllamaModelManageResponse"]>;

export type ViewerAuthStatusResponse = Served<Schemas["ViewerAuthStatusResponse"]>;

export type ViewerAuthLoginResponse = Served<Schemas["ViewerAuthLoginResponse"]>;

export type ToolAuthStatusResponse = Served<Schemas["ToolAuthStatusResponse"]>;

export type ToolAuthLoginResponse = Served<Schemas["ToolAuthLoginResponse"]>;

export type RestoreDatasetKind = "protein" | "phospho" | "phosprot" | "peptide";

export type RestoreMissingFile = {
  packageName: string;
  kind: RestoreDatasetKind;
  filename?: string | null;
  expectedPath?: string | null;
  message: string;
};

export type RestoreImportResponse = Served<Schemas["RestoreImportResponse"]>;
