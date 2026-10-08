import { registerStyleStore, styleTemplate, withStyle } from "../../lib/plotStyles";
import { AssistantAppearanceMount, AssistantSelect } from "../../components/AssistantFields";
import PlotDownloadControls from "../../components/PlotDownloadControls";
import OptionsLayout from "../../components/OptionsLayout";
import { MATPLOTLIB_CONTROLS, PLOTLY_DEFAULT_TEMPLATE_CONTROLS } from "../../lib/plotControlDefaults";
import { restorePlotDimensionCm, restorePlotDpi, iframeHeightForPlot } from "../../lib/plotLimits";
import PlotImage from "../../components/PlotImage";
import InteractivePlot from "../../components/InteractivePlot";
import NotebookDownload, { type RenderedNotebook } from "../../components/NotebookDownload";
import { withoutStaticSize } from "../../lib/plotRenderType";
import { SizeRow } from "../../components/PlotFields";
import CheckboxField from "../../components/CheckboxField";
import NumberField from "../../components/NumberField";
import { compactAdvancedPlotSettings as compactAdvancedSettings, migrateAdvancedSettingsMap } from "../../lib/plotSerialization";
import { methodDefaultScaling, pcaMethodLabel, SCALING_LABELS, scalingLabel, scalingValue } from "./pcaScaling";
import { collectColumns, csvDataUrl, rowsToQuotedCsv as rowsToCsv } from "../../lib/tableData";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { buildPlotUrl, getPeptideQuantityOptions, getQcPcaFeatures, getQcPlotOptions, getQcTable, isAbortError } from "../../lib/api";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import {
  coercePlotDownloadFormat,
  type PlotDownloadFormat,
  withPlotDownloadFilename,
  withPlotDownloadFormat,
} from "../../lib/plotDownload";
import { saveQcReportSettings } from "../../lib/reportState";
import { readPersistedUiState, writePersistedUiState } from "../../lib/persistedUiState";
import { getAdvancedPlotMode } from "../../lib/appSettings";
import { IS_VIEWER_MODE } from "../../lib/appMode";
import AdvancedPlotOptions, {
  type AdvancedPlotControlDefaults,
  type AdvancedPlotVisibleControls,
} from "../../components/plots/AdvancedPlotOptions";
import type {
  AdvancedPlotSettings,
  AnnotationKind,
  QcPcaFeatureSummary,
  QcTab,
  DataSource,
  DataSourceChoices,
} from "../../lib/types";
import {
  DATA_SOURCE_LABELS,
  dataSourceOptions,
  resolveDataSource,
  savedDataSource,
} from "../../lib/types";
import SelectField from "../../components/SelectField";
import PreviewTable from "../../components/PreviewTable";
import type { ContextMode } from "../../lib/types";
import LocalizationCutoffField from "../../components/LocalizationCutoffField";
import { useAdvancedPlotSignal } from "../../lib/useAdvancedPlotSignal";

type Props = {
  activeTab: QcTab;
  onWorkflowScopeChange?: (workflow: string) => void;
  onBoxplotContextModeChange?: (mode: ContextMode | null) => void;
  onPcaContextModeChange?: (mode: ContextMode | null) => void;
  onAbundanceContextModeChange?: (mode: ContextMode | null) => void;
  onCoverageContextModeChange?: (mode: ContextMode | null) => void;
};

type QcTableRequest = {
  tab: "coverage" | "boxplot" | "cv";
  params?: Record<string, string | number | boolean>;
};

type QcKind = AnnotationKind | "peptide" | "precursor";
type AdvancedPlotState = Partial<Record<QcTab, AdvancedPlotSettings>>;

function isAnnotationKind(kind: QcKind): kind is AnnotationKind {
  return kind === "protein" || kind === "phospho" || kind === "phosprot";
}

function workflowScopeFromKind(kind: QcKind): string {
  if (kind === "phospho") return "phosphosite";
  if (kind === "phosprot") return "phosphoprotein";
  if (kind === "peptide" || kind === "precursor") return "peptide";
  return "protein";
}

// The page's appearance settings apply whether the panel is open or not:
// advanced mode only shows the panel, it never switches the settings.
function advancedParam(settings: AdvancedPlotSettings): string | undefined {
  const compacted = compactAdvancedSettings(settings);
  return Object.keys(compacted).length ? JSON.stringify(compacted) : undefined;
}

function withAdvancedParams(
  params: Record<string, string | number | boolean>,
  advanced: string | undefined
): Record<string, string | number | boolean> {
  return { ...params, advanced: advanced ?? "" };
}

export default function QCPipelinePage({
  activeTab,
  onWorkflowScopeChange,
  onBoxplotContextModeChange,
  onPcaContextModeChange,
  onAbundanceContextModeChange,
  onCoverageContextModeChange,
}: Props) {
  const kindFieldId = useId();
  const [renderedNotebook, setRenderedNotebook] = useState<RenderedNotebook | null>(null);
  const [tableSnapshotToken, setTableSnapshotToken] = useState<string | null>(null);
  const persisted = useMemo(
    () => readPersistedUiState<Record<string, unknown>>("qc.pipeline.v1", {}),
    []
  );
  const persistedCoverage = (persisted.coverage as Record<string, unknown>) ?? {};
  const persistedHist = (persisted.hist as Record<string, unknown>) ?? {};
  const persistedBox = (persisted.box as Record<string, unknown>) ?? {};
  const persistedCv = (persisted.cv as Record<string, unknown>) ?? {};
  const persistedPca = (persisted.pca as Record<string, unknown>) ?? {};
  const persistedAbundance = (persisted.abundance as Record<string, unknown>) ?? {};
  const persistedCorrelation = (persisted.correlation as Record<string, unknown>) ?? {};
  // Versioned: settings saved before v2 carry the frame and grid defaults the
  // panel used to add to every first edit, and would now apply for good.
  const persistedAdvanced: AdvancedPlotState = migrateAdvancedSettingsMap(IS_VIEWER_MODE
    ? readPersistedUiState<AdvancedPlotState>("qc.advanced.v2", {})
    : (persisted.advancedV2 as AdvancedPlotState) ?? {});
  const [kind, setKind] = useState<QcKind>(() => {
    const value = String(persisted.kind ?? "protein").trim();
    if (value === "protein" || value === "phospho" || value === "phosprot" || value === "peptide" || value === "precursor") return value;
    return "protein";
  });
  const { datasets, availableKinds, kindOptions } = useCurrentDatasetsSnapshot();
  // Rebuilds plot and table requests when the phosphosite localization cutoff changes.
  const plotSignal = useAdvancedPlotSignal();
  const [conditionOptions, setConditionOptions] = useState<string[]>([]);
  const [sampleOptions, setSampleOptions] = useState<string[]>([]);
  const [sampleDisplayLabels, setSampleDisplayLabels] = useState<Record<string, string>>({});
  const [sampleDisplayLabelsWithId, setSampleDisplayLabelsWithId] = useState<Record<string, string>>({});
  // PCA is the only plot on this page that chooses its matrix: it cannot use
  // incomplete features, so the choice is a scientific one. Every other QC plot
  // describes the data as loaded and has no selector at all.
  const [dataSourceChoices, setDataSourceChoices] = useState<DataSourceChoices>({
    availableDataSources: ["data"],
    defaultDataSource: "data",
  });
  // Set only for a phosphoprotein dataset collapsed with `robust_site_median`.
  // The CV of a ratio to a site's own median is not the CV of an abundance, so
  // that one combination gets a warning under the plot.
  const [centredPhosprotValues, setCentredPhosprotValues] = useState(false);
  const [peptideQuantityColumns, setPeptideQuantityColumns] = useState<string[]>([]);
  const [peptideQuantityRequiresSelection, setPeptideQuantityRequiresSelection] = useState(false);
  const [peptideQuantityError, setPeptideQuantityError] = useState<string | null>(null);
  const [tableRows, setTableRows] = useState<Record<string, unknown>[]>([]);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState<string | null>(null);
  const [downloadFormat, setDownloadFormat] = useState<PlotDownloadFormat>(() =>
    coercePlotDownloadFormat(persisted.downloadFormat)
  );
  const [advancedModeEnabled, setAdvancedModeEnabled] = useState(() => getAdvancedPlotMode());
  const [advancedByTab, setAdvancedByTab] = useState<AdvancedPlotState>(() => persistedAdvanced);
  const [advancedRenderByTab, setAdvancedRenderByTab] = useState<AdvancedPlotState>(() => persistedAdvanced);

  const [coverage, setCoverage] = useState({
    quantityColumn: String(persistedCoverage.quantityColumn ?? ""),
    includeId: Boolean(persistedCoverage.includeId ?? false),
    header: true,
    legend: true,
    summary: Boolean(persistedCoverage.summary ?? false),
    text: Boolean(persistedCoverage.text ?? false),
    textSize: Number(persistedCoverage.textSize ?? 9),
    randomSeed: Number(persistedCoverage.randomSeed ?? 187),
    // The line at the number of features quantified in any sample. Its own
    // switch, because turning it off also gives the bars the full height.
    referenceLine: persistedCoverage.referenceLine !== false,
    widthCm: restorePlotDimensionCm(persistedCoverage.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedCoverage.heightCm, 10),
    dpi: restorePlotDpi(persistedCoverage.dpi, 300),
  });
  const [hist, setHist] = useState({
    header: true,
    legend: true,
    widthCm: restorePlotDimensionCm(persistedHist.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedHist.heightCm, 10),
    dpi: restorePlotDpi(persistedHist.dpi, 300),
  });
  const [box, setBox] = useState({
    mode: String(persistedBox.mode ?? "Mean"),
    outliers: Boolean(persistedBox.outliers ?? false),
    includeId: Boolean(persistedBox.includeId ?? false),
    header: true,
    legend: true,
    text: Boolean(persistedBox.text ?? false),
    textSize: Number(persistedBox.textSize ?? 9),
    widthCm: restorePlotDimensionCm(persistedBox.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedBox.heightCm, 10),
    dpi: restorePlotDpi(persistedBox.dpi, 300),
  });
  const [cv, setCv] = useState({
    outliers: Boolean(persistedCv.outliers ?? false),
    header: true,
    legend: true,
    text: Boolean(persistedCv.text ?? false),
    textSize: Number(persistedCv.textSize ?? 9),
    widthCm: restorePlotDimensionCm(persistedCv.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedCv.heightCm, 10),
    dpi: restorePlotDpi(persistedCv.dpi, 300),
  });
  // Whether the user has actually chosen, as opposed to a restored placeholder.
  // A made-up choice is indistinguishable from a real one, and "data" is always
  // available -- so inventing one makes the served default unreachable for ever.
  const pcaSourceChosen = useRef(savedDataSource(persistedPca.dataSource) !== null);
  const [pca, setPca] = useState({
    // "data" is a placeholder only while `pcaSourceChosen` is false; the ladder
    // default replaces it the first time the backend says which matrices exist.
    dataSource: savedDataSource(persistedPca.dataSource) ?? "data",
    type: String(persistedPca.type ?? "Normal"),
    header: true,
    legend: true,
    method: String(persistedPca.method ?? "PCA"),
    scaling: String(persistedPca.scaling ?? "auto"),
    plotDim: String(persistedPca.plotDim ?? "2D"),
    addEllipses: Boolean(persistedPca.addEllipses ?? false),
    clusterMethod: String(persistedPca.clusterMethod ?? "None"),
    clusterCount: Number(persistedPca.clusterCount ?? 3),
    colorBy: String(persistedPca.colorBy ?? "Condition"),
    umapNNeighbors: Number(persistedPca.umapNNeighbors ?? 15),
    umapMinDist: Number(persistedPca.umapMinDist ?? 0.1),
    tsnePerplexity: Number(persistedPca.tsnePerplexity ?? 30),
    tsneLearningRate: Number(persistedPca.tsneLearningRate ?? 200),
    dbscanEpsFactor: Number(persistedPca.dbscanEpsFactor ?? 0.5),
    dbscanMinSamples: Number(persistedPca.dbscanMinSamples ?? 2),
    randomState: Number(persistedPca.randomState ?? 42),
    widthCm: restorePlotDimensionCm(persistedPca.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedPca.heightCm, 10),
    dpi: restorePlotDpi(persistedPca.dpi, 300),
  });
  const [abundance, setAbundance] = useState({
    type: String(persistedAbundance.type ?? "Normal"),
    header: true,
    legend: true,
    condition: String(persistedAbundance.condition ?? "All Conditions"),
    widthCm: restorePlotDimensionCm(persistedAbundance.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedAbundance.heightCm, 10),
    dpi: restorePlotDpi(persistedAbundance.dpi, 300),
  });
  const [correlation, setCorrelation] = useState({
    method: String(persistedCorrelation.method ?? "Matrix"),
    includeId: Boolean(persistedCorrelation.includeId ?? false),
    fullRange: Boolean(persistedCorrelation.fullRange ?? false),
    widthCm: restorePlotDimensionCm(persistedCorrelation.widthCm, 20),
    heightCm: restorePlotDimensionCm(persistedCorrelation.heightCm, 16),
    dpi: restorePlotDpi(persistedCorrelation.dpi, 400),
  });

  useEffect(() => {
    const nextState: Record<string, unknown> = {
      kind,
      downloadFormat,
      coverage,
      hist,
      box,
      cv,
      pca,
      abundance,
      correlation,
    };
    if (!IS_VIEWER_MODE) {
      nextState.advancedV2 = advancedByTab;
    } else {
      writePersistedUiState("qc.advanced.v2", advancedByTab);
    }
    writePersistedUiState("qc.pipeline.v1", nextState);
  }, [kind, downloadFormat, coverage, hist, box, cv, pca, abundance, correlation, advancedByTab]);

  useEffect(() => {
    const refresh = () => setAdvancedModeEnabled(getAdvancedPlotMode());
    window.addEventListener("focus", refresh);
    window.addEventListener("storage", refresh);
    window.addEventListener("copylot:advancedPlotModeChanged", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("storage", refresh);
      window.removeEventListener("copylot:advancedPlotModeChanged", refresh);
    };
  }, []);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setAdvancedRenderByTab(advancedByTab);
    }, 350);
    return () => window.clearTimeout(timeout);
  }, [advancedByTab]);

  useEffect(() => {
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) return;
    saveQcReportSettings(kind, {
      coverage,
      hist,
      box,
      cv,
      pca,
      abundance,
      correlation,
    });
  }, [kind, availableKinds, coverage, hist, box, cv, pca, abundance, correlation]);

  useEffect(() => {
    if ((kind === "peptide" || kind === "precursor") && datasets?.peptide) {
      saveQcReportSettings("peptide", { coverage });
    }
  }, [kind, datasets?.peptide, coverage]);

  useEffect(() => {
    onAbundanceContextModeChange?.(activeTab === "abundance" ? { condition: abundance.condition } : null);
  }, [activeTab, abundance.condition, onAbundanceContextModeChange]);

  useEffect(() => {
    onCoverageContextModeChange?.(activeTab === "coverage"
      ? { level: kind === "precursor" ? "precursor" : "peptide", quantityColumn: coverage.quantityColumn } : null);
  }, [activeTab, kind, coverage.quantityColumn, onCoverageContextModeChange]);

  const activeKindOptions = useMemo<Array<{ value: QcKind; label: string }>>(() => {
    if (activeTab !== "coverage") return kindOptions;
    const options: Array<{ value: QcKind; label: string }> = [...kindOptions];
    if (datasets?.peptide) {
      options.push({ value: "peptide", label: "Peptide" });
      options.push({ value: "precursor", label: "Precursor" });
    }
    return options;
  }, [activeTab, kindOptions, datasets]);

  useEffect(() => {
    if (activeKindOptions.length === 0) {
      setConditionOptions([]);
      return;
    }
    if (!activeKindOptions.some((option) => option.value === kind)) {
      setKind(activeKindOptions[0].value);
    }
  }, [activeKindOptions, kind]);

  useEffect(() => {
    if ((kind !== "peptide" && kind !== "precursor") || !datasets?.peptide) {
      setPeptideQuantityColumns([]);
      setPeptideQuantityRequiresSelection(false);
      setPeptideQuantityError(null);
      return;
    }
    const controller = new AbortController();
    getPeptideQuantityOptions({ signal: controller.signal })
      .then((payload) => {
        setPeptideQuantityColumns(payload.columns);
        setPeptideQuantityRequiresSelection(payload.requiresSelection);
        setPeptideQuantityError(
          payload.columns.length === 0
            ? "No supported peptide abundance column was found in this dataset."
            : null
        );
        setCoverage((current) => {
          if (current.quantityColumn && payload.columns.includes(current.quantityColumn)) return current;
          return { ...current, quantityColumn: payload.defaultColumn ?? "" };
        });
      })
      .catch((error) => {
        if (isAbortError(error)) return;
        setPeptideQuantityColumns([]);
        setPeptideQuantityRequiresSelection(false);
        setPeptideQuantityError(
          error instanceof Error ? error.message : "Failed to load peptide abundance columns"
        );
      });
    return () => controller.abort();
  }, [kind, datasets?.peptide]);

  useEffect(() => {
    if (!onWorkflowScopeChange) return;
    if (activeKindOptions.length === 0) {
      onWorkflowScopeChange("");
      return;
    }
    onWorkflowScopeChange(workflowScopeFromKind(kind));
  }, [activeKindOptions, kind, onWorkflowScopeChange]);

  useEffect(() => {
    if (!onBoxplotContextModeChange) return;
    if (activeTab !== "boxplot") {
      onBoxplotContextModeChange(null);
      return;
    }
    onBoxplotContextModeChange({ mode: String(box.mode || "").trim() });
  }, [activeTab, box.mode, onBoxplotContextModeChange]);

  useEffect(() => {
    if (!onPcaContextModeChange) return;
    if (activeTab !== "pca") {
      onPcaContextModeChange(null);
      return;
    }
    const method = String(pca.method || "").trim();
    const plotDim = String(pca.plotDim || "").trim();
    const type = String(pca.type || "").trim();
    const mode: ContextMode = {
      method: method || "PCA",
      plotDim: plotDim || "2D",
      type: type || "Normal",
      dataSource: pca.dataSource,
      scaling: pca.scaling,
    };
    onPcaContextModeChange(mode);
  }, [activeTab, pca.dataSource, pca.method, pca.plotDim, pca.type, pca.scaling, onPcaContextModeChange]);

  const [pcaFeatures, setPcaFeatures] = useState<QcPcaFeatureSummary | null>(null);

  // Dimensionality reduction drops any feature with a missing value, so the
  // projection can rest on a small, abundance-biased subset. Surface that.
  useEffect(() => {
    if (activeTab !== "pca" || !isAnnotationKind(kind) || !availableKinds.includes(kind)) {
      setPcaFeatures(null);
      return;
    }
    const controller = new AbortController();
    getQcPcaFeatures(
      kind,
      {
        dataSource: pca.dataSource,
        plotDim: pca.plotDim,
        addEllipses: pca.addEllipses,
        method: pca.method,
        scaling: pca.scaling,
        colorBy: pca.colorBy,
        clusterMethod: pca.clusterMethod,
        clusterCount: pca.clusterCount,
        dbscanEpsFactor: pca.dbscanEpsFactor,
        dbscanMinSamples: pca.dbscanMinSamples,
        umapNNeighbors: pca.umapNNeighbors,
        umapMinDist: pca.umapMinDist,
        tsnePerplexity: pca.tsnePerplexity,
        tsneLearningRate: pca.tsneLearningRate,
        randomState: pca.randomState,
      },
      { signal: controller.signal }
    )
      .then((payload) => {
        setPcaFeatures(payload);
      })
      .catch((error) => {
        if (!isAbortError(error)) setPcaFeatures(null);
      });
    return () => {
      controller.abort();
    };
    // Every projection control is a dependency: the notice below the plot names
    // the groups that got no ellipse, and that answer changes when the points do.
  }, [
    activeTab,
    kind,
    availableKinds,
    pca.dataSource,
    pca.plotDim,
    pca.addEllipses,
    pca.method,
    pca.scaling,
    pca.colorBy,
    pca.clusterMethod,
    pca.clusterCount,
    pca.dbscanEpsFactor,
    pca.dbscanMinSamples,
    pca.umapNNeighbors,
    pca.umapMinDist,
    pca.tsnePerplexity,
    pca.tsneLearningRate,
    pca.randomState,
  ]);

  useEffect(() => {
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) {
      setConditionOptions([]);
      setSampleOptions([]);
      setSampleDisplayLabels({});
      setSampleDisplayLabelsWithId({});
      setCentredPhosprotValues(false);
      return;
    }
    const controller = new AbortController();
    getQcPlotOptions(kind, { signal: controller.signal })
      .then((payload) => {
        const unique = Array.from(new Set(payload.conditions.map((value) => value.trim()).filter(Boolean)));
        setConditionOptions(unique);
        const samples = Array.from(new Set((payload.samples ?? []).map((value) => value.trim()).filter(Boolean)));
        setSampleOptions(samples);
        setSampleDisplayLabels(payload.sampleLabels ?? {});
        setSampleDisplayLabelsWithId(payload.sampleLabelsWithId ?? {});
        setDataSourceChoices({
          availableDataSources: payload.availableDataSources ?? ["data"],
          defaultDataSource: payload.defaultDataSource ?? "data",
        });
        setCentredPhosprotValues(Boolean(payload.centredPhosprotValues));
        // Read and flip the ref here, not inside the updater: StrictMode
        // invokes an updater twice from the same base state, and a flag flipped
        // inside it sends the second pass down the other branch.
        const takeDefault = !pcaSourceChosen.current;
        pcaSourceChosen.current = true;
        setPca((current) => {
          const resolved = takeDefault
            ? payload.defaultDataSource ?? resolveDataSource(current.dataSource, payload)
            : resolveDataSource(current.dataSource, payload);
          return resolved === current.dataSource ? current : { ...current, dataSource: resolved };
        });
      })
      .catch((error) => {
        if (isAbortError(error)) return;
        setConditionOptions([]);
        setSampleOptions([]);
        setSampleDisplayLabels({});
        setSampleDisplayLabelsWithId({});
        setCentredPhosprotValues(false);
      });
    return () => {
      controller.abort();
    };
  }, [kind, availableKinds]);

  useEffect(() => {
    setAbundance((prev) => {
      if (prev.condition === "All Conditions") return prev;
      if (conditionOptions.includes(prev.condition)) return prev;
      return { ...prev, condition: "All Conditions" };
    });
  }, [conditionOptions]);

  const tableRequest = useMemo<QcTableRequest | null>(() => {
    void plotSignal;
    if (!isAnnotationKind(kind)) return null;
    if (activeTab === "coverage") {
      const params: Record<string, string | number | boolean> = {
        summary: coverage.summary,
      };
      return {
        tab: "coverage",
        params,
      };
    }
    if (activeTab === "boxplot") {
      const params: Record<string, string | number | boolean> = {
        mode: box.mode,
      };
      return {
        tab: "boxplot",
        params,
      };
    }
    if (activeTab === "cv") {
      return {
        tab: "cv",
        params: undefined,
      };
    }
    return null;
  }, [kind, activeTab, coverage.summary, box.mode, plotSignal]);


  const activeAdvancedSettings = advancedByTab[activeTab] ?? styleTemplate() ?? {};
  // Named styles and "this style on every plot" (lib/plotStyles.ts) reach these settings here.
  const styleStoreState = useRef({ tab: activeTab, byTab: advancedByTab });
  useEffect(() => { styleStoreState.current = { tab: activeTab, byTab: advancedByTab }; }, [activeTab, advancedByTab]);
  useEffect(() => registerStyleStore("qc", {
    active: () => styleStoreState.current.byTab[styleStoreState.current.tab] ?? styleTemplate() ?? {},
    setActive: (settings) => setAdvancedByTab((prev) => ({ ...prev, [styleStoreState.current.tab]: settings })),
    setAll: (style) => {
      setAdvancedByTab((prev) => Object.fromEntries(Object.entries(prev).map(([tab, value]) => [tab, withStyle(value, style)])));
      return Object.keys(styleStoreState.current.byTab).length;
    },
  }), []);
  const activeAdvancedRenderSettings = useMemo(
    () => advancedRenderByTab[activeTab] ?? styleTemplate() ?? {},
    [activeTab, advancedRenderByTab]
  );
  const activeConditionDisplayLabels = useMemo(
    () => Object.fromEntries(conditionOptions.map((condition) => [condition, condition])),
    [conditionOptions]
  );
  const activeSampleDisplayLabels = useMemo(() => {
    const rawLabels = Object.fromEntries(sampleOptions.map((sample) => [sample, sample]));
    if (activeTab === "coverage" && !coverage.summary) {
      return coverage.includeId ? sampleDisplayLabelsWithId : sampleDisplayLabels;
    }
    if (activeTab === "boxplot" && box.mode === "Single") {
      return box.includeId ? sampleDisplayLabelsWithId : sampleDisplayLabels;
    }
    if (activeTab === "correlation") {
      return correlation.includeId ? sampleDisplayLabelsWithId : sampleDisplayLabels;
    }
    return rawLabels;
  }, [
    activeTab,
    box.includeId,
    box.mode,
    correlation.includeId,
    coverage.includeId,
    coverage.summary,
    sampleDisplayLabels,
    sampleDisplayLabelsWithId,
    sampleOptions,
  ]);
  const activeAdvancedVisibleControls = useMemo<AdvancedPlotVisibleControls>(() => {
    const base: AdvancedPlotVisibleControls = {
      textElements: true,
      tickControls: true,
      legendControls: false,
      referenceLineColor: false,
      conditionLabels: false,
      sampleLabels: false,
      conditionColors: false,
      boxplotStyle: false,
      boxplotOutliers: false,
      correlationGradient: false,
    };
    if (activeTab === "coverage") {
      return {
        ...base,
        legendControls: Boolean(coverage.legend && !coverage.summary),
        // The line is switched in the coverage options; its look is here, and
        // only while there is a line to style.
        referenceLineColor: coverage.referenceLine,
        referenceLineToggle: false,
        conditionLabels: true,
        sampleLabels: !coverage.summary,
        conditionColors: true,
        // The jittered dots over the summary bars are the only points here, and
        // they are drawn without a plot-chosen colour (`color_default="black"`),
        // so the Points card's dot colour does reach them.
        markerStyle: Boolean(coverage.summary),
        valueLabels: true,
      };
    }
    if (activeTab === "histogram") {
      return {
        ...base,
        legendControls: Boolean(hist.legend),
        conditionLabels: true,
        conditionColors: true,
      };
    }
    if (activeTab === "boxplot") {
      return {
        ...base,
        legendControls: Boolean(box.legend),
        conditionLabels: true,
        sampleLabels: String(box.mode).toLowerCase() === "single",
        conditionColors: true,
        boxplotStyle: true,
        boxplotOutliers: Boolean(box.outliers),
        valueLabels: true,
      };
    }
    if (activeTab === "cv") {
      return {
        ...base,
        legendControls: Boolean(cv.legend),
        conditionLabels: true,
        conditionColors: true,
        boxplotStyle: true,
        boxplotOutliers: Boolean(cv.outliers),
        valueLabels: true,
      };
    }
    if (activeTab === "pca") {
      const colorBy = String(pca.colorBy || "Condition").trim().toLowerCase();
      const clusterMethod = String(pca.clusterMethod || "None").trim().toLowerCase();
      const usesConditionGroups = colorBy !== "cluster" || clusterMethod === "none";
      return {
        ...base,
        legendControls: Boolean(pca.legend),
        conditionLabels: usesConditionGroups,
        conditionColors: usesConditionGroups,
        markerStyle: true,
        // Every point is drawn in its group's colour from the condition
        // palette (`_advanced_condition_colors`), which `resolve_marker` takes
        // over any general `markerColor` -- so there is no dot colour to set
        // here, in either renderer.
        markerColor: false,
        // One trace per condition, so each can be sized and shaped on its own.
        conditionMarkers: usesConditionGroups,
      };
    }
    if (activeTab === "abundance") {
      return {
        ...base,
        legendControls: Boolean(abundance.legend),
        conditionLabels: true,
        conditionColors: true,
        markerStyle: true,
        // One curve per condition, each in that condition's palette colour,
        // which wins over `markerColor` in both renderers.
        markerColor: false,
        conditionMarkers: true,
      };
    }
      return {
        ...base,
        sampleLabels: true,
        correlationGradient: true,
      };
  }, [
    activeTab,
    abundance.legend,
    box.legend,
    box.mode,
    box.outliers,
    coverage.legend,
    coverage.referenceLine,
    coverage.summary,
    cv.legend,
    cv.outliers,
    hist.legend,
    pca.clusterMethod,
    pca.colorBy,
    pca.legend,
  ]);
  // The plot as drawn: matplotlib for every static QC figure, Plotly's default
  // template for the interactive PCA and abundance plots.
  const activeAdvancedControlDefaults = useMemo<AdvancedPlotControlDefaults>(() => {
    if (activeTab === "pca" && pca.type === "Interactive") return PLOTLY_DEFAULT_TEMPLATE_CONTROLS;
    if (activeTab === "abundance" && abundance.type === "Interactive") return PLOTLY_DEFAULT_TEMPLATE_CONTROLS;
    return MATPLOTLIB_CONTROLS;
  }, [activeTab, abundance.type, pca.type]);
  const activeAdvancedParam = useMemo(
    () => advancedParam(activeAdvancedRenderSettings),
    [activeAdvancedRenderSettings]
  );

  const plotView = useMemo(() => {
    void plotSignal;
    if (!activeKindOptions.some((option) => option.value === kind)) return null;
    if (activeTab === "coverage") {
      if ((kind === "peptide" || kind === "precursor") && (!coverage.quantityColumn || peptideQuantityError)) return null;
      return {
        mode: "image" as const,
        url: buildPlotUrl(`/api/plots/qc/${kind}/coverage.png`, withAdvancedParams(coverage, activeAdvancedParam)),
      };
    }
    if (activeTab === "histogram") {
      return {
        mode: "image" as const,
        url: buildPlotUrl(`/api/plots/qc/${kind}/intensity-histogram.png`, withAdvancedParams(hist, activeAdvancedParam)),
      };
    }
    if (activeTab === "boxplot") {
      return {
        mode: "image" as const,
        url: buildPlotUrl(`/api/plots/qc/${kind}/boxplot.png`, withAdvancedParams(box, activeAdvancedParam)),
      };
    }
    if (activeTab === "cv") {
      return {
        mode: "image" as const,
        url: buildPlotUrl(`/api/plots/qc/${kind}/cv.png`, withAdvancedParams(cv, activeAdvancedParam)),
      };
    }
    if (activeTab === "pca") {
      const { type, ...params } = pca;
      const plotParams = withAdvancedParams(params, activeAdvancedParam);
      if (type === "Interactive") {
        return {
          mode: "html" as const,
          url: buildPlotUrl(`/api/plots/qc/${kind}/pca-interactive.html`, withoutStaticSize(plotParams)),
        };
      }
      return { mode: "image" as const, url: buildPlotUrl(`/api/plots/qc/${kind}/pca.png`, plotParams) };
    }
    if (activeTab === "abundance") {
      const { type, ...params } = abundance;
      const plotParams = withAdvancedParams(params, activeAdvancedParam);
      if (type === "Interactive") {
        return {
          mode: "html" as const,
          url: buildPlotUrl(`/api/plots/qc/${kind}/abundance-interactive.html`, withoutStaticSize(plotParams)),
        };
      }
      return { mode: "image" as const, url: buildPlotUrl(`/api/plots/qc/${kind}/abundance.png`, plotParams) };
    }
    return {
      mode: "image" as const,
      url: buildPlotUrl(`/api/plots/qc/${kind}/correlation.png`, withAdvancedParams(correlation, activeAdvancedParam)),
    };
  }, [
    activeTab,
    kind,
    coverage,
    hist,
    box,
    cv,
    pca,
    abundance,
    correlation,
    activeKindOptions,
    activeAdvancedParam,
    peptideQuantityError,
    plotSignal,
  ]);

  const plotDownloadUrl = useMemo(() => {
    if (!plotView || plotView.mode !== "image") return "";
    return withPlotDownloadFormat(plotView.url, downloadFormat);
  }, [plotView, downloadFormat]);
  const plotDownloadFilename = useMemo(() => {
    if (!plotView || plotView.mode !== "image") return "";
    return withPlotDownloadFilename(`qc_${activeTab}_${kind}.png`, downloadFormat);
  }, [plotView, activeTab, kind, downloadFormat]);

  // The interactive plots are drawn at the renderer's own size (10 cm high)
  // and then fill the frame; the static figure's height is not theirs.
  const interactiveHeightPx = cmToIframeHeight(10);

  const activePlotTitle = useMemo(() => {
    if (activeTab === "pca") {
      return `${pcaMethodLabel(pca.method)} Plot`;
    }
    return tabTitle(activeTab);
  }, [activeTab, pca.method]);

  const pairedNotebook = (["coverage", "boxplot", "cv", "histogram", "abundance", "correlation"].includes(activeTab)
    || activeTab === "pca")
    && (plotView?.mode === "image" || activeTab === "abundance" || activeTab === "pca")
    && (kind === "protein" || kind === "phospho" || kind === "phosprot"
      || (activeTab === "coverage" && (kind === "peptide" || kind === "precursor")));
  const notebookToken = pairedNotebook && renderedNotebook?.url === plotView?.url
    ? renderedNotebook?.token : null;

  useEffect(() => {
    if (!isAnnotationKind(kind) || !availableKinds.includes(kind)) {
      setTableRows([]);
      setTableError(null);
      setTableLoading(false);
      return;
    }
    if (!tableRequest) {
      setTableRows([]);
      setTableError(null);
      setTableLoading(false);
      return;
    }

    const controller = new AbortController();
    setTableLoading(true);
    setTableRows([]);
    setTableError(null);

    getQcTable(kind, tableRequest.tab, { ...tableRequest.params, ...(notebookToken ? { snapshot: notebookToken } : {}) }, { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) {
          setTableRows(response.rows ?? []);
          setTableSnapshotToken(notebookToken ?? null);
        }
      })
      .catch((err) => {
        if (isAbortError(err)) return;
        setTableRows([]);
        setTableError(err instanceof Error ? err.message : "Failed to load table");
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        setTableLoading(false);
      });

    return () => {
      controller.abort();
    };
  }, [kind, tableRequest, availableKinds, pairedNotebook, notebookToken]);

  const tableCsvUrl = useMemo(() => {
    if (tableLoading || tableError || (notebookToken && tableSnapshotToken !== notebookToken)) return null;
    if (!tableRequest || tableRows.length === 0) return null;
    const columns = collectColumns(tableRows);
    if (columns.length === 0) return null;
    return csvDataUrl(rowsToCsv(tableRows, columns));
  }, [tableRequest, tableRows, tableLoading, tableError, notebookToken, tableSnapshotToken]);


  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">QC Pipeline</h2>
        <div className="mt-4 max-w-xs">
            <label htmlFor={kindFieldId} className="mb-2 block text-sm font-medium text-slate-700">Dataset level</label>
            <AssistantSelect
            id={kindFieldId}
            value={activeKindOptions.length === 0 ? "" : kind}
            onChange={(e) => setKind(e.target.value as QcKind)}
            disabled={activeKindOptions.length === 0}
            className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:bg-slate-100"
          >
            {activeKindOptions.length === 0 ? (
              <option value="">No dataset available</option>
            ) : (
              activeKindOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))
            )}
          </AssistantSelect>
        </div>
        <LocalizationCutoffField kind={kind} className="mt-4 max-w-xs" />
      </section>

      {activeKindOptions.length === 0 ? (
        <section className="rounded-2xl border border-sky-200 bg-sky-50 px-6 py-4 text-sm text-sky-800">
          Upload a protein, phospho, phosphoprotein, or peptide dataset in the Data tab to enable QC plotting.
        </section>
      ) : null}

      {activeKindOptions.length > 0 ? (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-semibold text-slate-900">Options</h3>
        <div className="mt-4">{renderOptions()}</div>
        {(kind === "peptide" || kind === "precursor") && peptideQuantityError ? (
          <div className="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {peptideQuantityError}
          </div>
        ) : null}
      </section>
      ) : null}

      {activeKindOptions.length > 0 ? (
        <AssistantAppearanceMount visible={advancedModeEnabled}>
        <AdvancedPlotOptions
          key={activeTab}
          value={activeAdvancedSettings}
          onChange={(next) => setAdvancedByTab((prev) => ({ ...prev, [activeTab]: next }))}
          conditionOptions={conditionOptions}
          conditionDisplayLabels={activeConditionDisplayLabels}
          sampleOptions={sampleOptions}
          sampleDisplayLabels={activeSampleDisplayLabels}
          visibleControls={activeAdvancedVisibleControls}
          controlDefaults={activeAdvancedControlDefaults}
        />
        </AssistantAppearanceMount>
      ) : null}

      {activeKindOptions.length > 0 ? (
      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-semibold text-slate-900">{activePlotTitle}</h3>
          {plotView?.mode === "image" ? (
            <div className="flex flex-wrap items-center gap-2">
              <PlotDownloadControls label="Plot" format={downloadFormat} onFormatChange={setDownloadFormat}
                href={plotDownloadUrl} filename={plotDownloadFilename} />
              {pairedNotebook ? (
                <NotebookDownload key={plotView.url} plotUrl={plotView.url} rendered={renderedNotebook} />
              ) : null}
            </div>
          ) : plotView ? (
            <div className="flex flex-wrap items-center gap-2">
            <a
              href={plotView.url}
              target="_blank"
              rel="noreferrer"
              className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
            >
              Open Interactive Plot
            </a>
            {pairedNotebook ? <NotebookDownload key={plotView.url} plotUrl={plotView.url} rendered={renderedNotebook} /> : null}
            </div>
          ) : null}
        </div>
        <div className="mt-4">
          {plotView?.mode === "image" && plotView.url ? (
            <PlotImage url={plotView.url} alt={activePlotTitle}
              onRendered={(url, token) => setRenderedNotebook({ url, token })} />
          ) : plotView && pairedNotebook ? (
            <InteractivePlot url={plotView.url} title={`${activePlotTitle} interactive plot`} height={interactiveHeightPx}
              onRendered={(url, token) => setRenderedNotebook({ url, token })} />
          ) : plotView ? (
            <iframe
              sandbox="allow-scripts allow-downloads"
              key={plotView.url}
              src={plotView.url}
              title={`${activePlotTitle} interactive plot`}
              className="w-full rounded-xl border border-slate-200"
              style={{ height: `${interactiveHeightPx}px` }}
            />
          ) : (
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-sm text-slate-500">
              No plot available for the selected dataset.
            </div>
          )}
        </div>
        {activeTab === "cv" && kind === "phosprot" && centredPhosprotValues ? (
          <CentredCvNotice />
        ) : null}
      </section>
      ) : null}

      {activeKindOptions.length > 0 && tableRequest ? (
        <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-slate-900">Summary Table</h3>
            <div className="flex flex-wrap items-center gap-2">
            {tableCsvUrl ? (
              <a
                href={tableCsvUrl}
                download={`qc_${activeTab}_${kind}_summary.csv`}
                className="rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-50"
              >
                Download CSV
              </a>
            ) : null}
            {pairedNotebook && plotView ? (
              <NotebookDownload key={plotView.url} plotUrl={plotView.url}
                rendered={!tableLoading && !tableError && tableSnapshotToken === notebookToken ? renderedNotebook : null} />
            ) : null}
            </div>
          </div>
          <div className="mt-4">
            {tableLoading ? (
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">
                Loading table...
              </div>
            ) : tableError ? (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {tableError}
              </div>
            ) : (
              <PreviewTable rows={tableRows} emptyText="No summary rows available." plotSummary />
            )}
          </div>
        </section>
      ) : null}
    </div>
  );

  function renderOptions() {
    if (activeTab === "coverage") {
      return (
        <OptionsLayout order="toggles-fields-size"
          toggles={[
            <CheckboxField assistant={false} key="id" label="Toggle IDs" checked={coverage.includeId} onChange={(v) => setCoverage({ ...coverage, includeId: v })} />,
            <CheckboxField assistant={false} key="summary" label="Summary Type" checked={coverage.summary} onChange={(v) => setCoverage({ ...coverage, summary: v })} />,
            <CheckboxField assistant={false} key="text" label="Toggle Text" checked={coverage.text} onChange={(v) => setCoverage({ ...coverage, text: v })} />,
            <CheckboxField assistant={false} key="reference-line" label="Total Line" checked={coverage.referenceLine} onChange={(v) => setCoverage({ ...coverage, referenceLine: v })} />,
          ]}
          fields={[
            ...((kind === "peptide" || kind === "precursor")
              ? [
                  <SelectField
                    key="quantity-column"
                    label="Abundance Column"
                    value={coverage.quantityColumn}
                    onChange={(value) => setCoverage({ ...coverage, quantityColumn: value })}
                    options={peptideQuantityColumns}
                    placeholder={peptideQuantityRequiresSelection ? "Select abundance column" : undefined}
                  />,
                ]
              : []),
            ...(coverage.summary
              ? [
                  <NumberField assistant={false}
                    key="random-seed"
                    label="Random Seed"
                    value={coverage.randomSeed}
                    onChange={(v) => setCoverage({ ...coverage, randomSeed: Math.max(0, Math.round(v)) })}
                  />,
                ]
              : []),
          ]}
          size={
            <SizeRow
              dpi={coverage.dpi}
              heightCm={coverage.heightCm}
              widthCm={coverage.widthCm}
              onDpiChange={(v) => setCoverage({ ...coverage, dpi: v })}
              onHeightChange={(v) => setCoverage({ ...coverage, heightCm: v })}
              onWidthChange={(v) => setCoverage({ ...coverage, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "histogram") {
      return (
        <OptionsLayout order="toggles-fields-size"
          toggles={[
          ]}
          size={
            <SizeRow
              dpi={hist.dpi}
              heightCm={hist.heightCm}
              widthCm={hist.widthCm}
              onDpiChange={(v) => setHist({ ...hist, dpi: v })}
              onHeightChange={(v) => setHist({ ...hist, heightCm: v })}
              onWidthChange={(v) => setHist({ ...hist, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "boxplot") {
      return (
        <OptionsLayout order="toggles-fields-size"
          toggles={[
            <CheckboxField assistant={false} key="outliers" label="Toggle Outliers" checked={box.outliers} onChange={(v) => setBox({ ...box, outliers: v })} />,
            <CheckboxField assistant={false} key="id" label="Toggle IDs" checked={box.includeId} onChange={(v) => setBox({ ...box, includeId: v })} />,
            <CheckboxField assistant={false} key="text" label="Toggle Text" checked={box.text} onChange={(v) => setBox({ ...box, text: v })} />,
          ]}
          fields={[
            <SelectField
              key="type"
              label="Type"
              value={box.mode}
              onChange={(value) => setBox({ ...box, mode: value })}
              options={["Mean", "Single"]}
            />,
          ]}
          size={
            <SizeRow
              dpi={box.dpi}
              heightCm={box.heightCm}
              widthCm={box.widthCm}
              onDpiChange={(v) => setBox({ ...box, dpi: v })}
              onHeightChange={(v) => setBox({ ...box, heightCm: v })}
              onWidthChange={(v) => setBox({ ...box, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "cv") {
      return (
        <OptionsLayout order="toggles-fields-size"
          toggles={[
            <CheckboxField assistant={false} key="outliers" label="Toggle Outliers" checked={cv.outliers} onChange={(v) => setCv({ ...cv, outliers: v })} />,
            <CheckboxField assistant={false} key="text" label="Toggle Text" checked={cv.text} onChange={(v) => setCv({ ...cv, text: v })} />,
          ]}
          fields={[
          ]}
          size={
            <SizeRow
              dpi={cv.dpi}
              heightCm={cv.heightCm}
              widthCm={cv.widthCm}
              onDpiChange={(v) => setCv({ ...cv, dpi: v })}
              onHeightChange={(v) => setCv({ ...cv, heightCm: v })}
              onWidthChange={(v) => setCv({ ...cv, widthCm: v })}
            />
          }
        />
      );
    }

    if (activeTab === "pca") {
      const clusterMethodOptions = ["None", "KMeans", "Agglomerative", "DBSCAN"];
      const showDimensions = pca.method === "PCA";
      const showClusteringControls = pca.method !== "PCA";
      const colorByOptions = pca.clusterMethod === "None" ? ["Condition"] : ["Condition", "Cluster"];
      const showClusterCount =
        showClusteringControls &&
        (pca.clusterMethod === "KMeans" || pca.clusterMethod === "Agglomerative");
      const showDbscan = showClusteringControls && pca.clusterMethod === "DBSCAN";
      const showUmap = pca.method === "UMAP";
      const showTsne = pca.method === "t-SNE";
      const showRandomState = showUmap || showTsne;
      const showEllipsesToggle = pca.plotDim === "2D";

      return (
        <div className="space-y-4">
          <PcaFeatureNotice summary={pcaFeatures} dataSource={pca.dataSource} />
        <OptionsLayout order="toggles-fields-size"
          toggles={[
            ...(showEllipsesToggle
              ? [
                  <CheckboxField assistant={false}
                    key="ellipses"
                    label="Add Ellipses (2D)"
                    checked={pca.addEllipses}
                    onChange={(v) => setPca({ ...pca, addEllipses: v })}
                  />,
                ]
              : []),
          ]}
          fields={[
            <SelectField
              key="data-source"
              label="Data Source"
              value={DATA_SOURCE_LABELS[pca.dataSource as DataSource]}
              onChange={(value) => {
                pcaSourceChosen.current = true;
                setPca({
                  ...pca,
                  dataSource:
                    (Object.keys(DATA_SOURCE_LABELS) as DataSource[]).find(
                      (key) => DATA_SOURCE_LABELS[key] === value
                    ) ?? "data",
                });
              }}
              options={dataSourceOptions(dataSourceChoices).map((option) => option.label)}
            />,
            <SelectField
              key="method"
              label="Method"
              value={pca.method}
              onChange={(value) => {
                const nextMethod = value || "PCA";
                setPca({
                  ...pca,
                  method: nextMethod,
                  plotDim: nextMethod === "PCA" ? pca.plotDim : "2D",
                  addEllipses: pca.addEllipses,
                  clusterMethod: nextMethod === "PCA" ? "None" : pca.clusterMethod,
                  colorBy: nextMethod === "PCA" ? "Condition" : pca.colorBy,
                  // Each method has an established default scaling, and the
                  // selector now names the scaling rather than "method
                  // default" -- so switching method has to move the selection,
                  // or the new method would silently run on the old method's
                  // convention.
                  scaling: methodDefaultScaling(nextMethod),
                });
              }}
              options={["PCA", "UMAP", "t-SNE"]}
            />,
            <SelectField
              key="scaling"
              label="Feature scaling"
              value={scalingLabel(pca.scaling, pca.method)}
              onChange={(value) => setPca({ ...pca, scaling: scalingValue(value) })}
              options={[...SCALING_LABELS]}
            />,
            <SelectField
              key="type"
              label="Type"
              value={pca.type}
              onChange={(value) => setPca({ ...pca, type: value })}
              options={["Normal", "Interactive"]}
            />,
            ...(showDimensions
              ? [
                  <SelectField
                    key="dim"
                    label="Dimensions"
                    value={pca.plotDim}
                    onChange={(value) => setPca({ ...pca, plotDim: value })}
                    options={["2D", "3D"]}
                  />,
                ]
              : []),
            ...(showClusteringControls
              ? [
                  <SelectField
                    key="cluster-method"
                    label="Clustering"
                    value={pca.clusterMethod}
                    onChange={(value) => {
                      const nextClusterMethod = value || "None";
                      setPca({
                        ...pca,
                        clusterMethod: nextClusterMethod,
                        colorBy: nextClusterMethod === "None" ? "Condition" : pca.colorBy,
                      });
                    }}
                    options={clusterMethodOptions}
                  />,
                  <SelectField
                    key="color-by"
                    label="Color By"
                    value={colorByOptions.includes(pca.colorBy) ? pca.colorBy : "Condition"}
                    onChange={(value) => setPca({ ...pca, colorBy: value || "Condition" })}
                    options={colorByOptions}
                  />,
                ]
              : []),
            ...(showClusterCount
              ? [
                  <NumberField assistant={false}
                    key="cluster-count"
                    label="Cluster Count"
                    value={pca.clusterCount}
                    onChange={(v) =>
                      setPca({ ...pca, clusterCount: Math.max(2, Math.min(20, Math.round(v))) })
                    }
                  />,
                ]
              : []),
            ...(showDbscan
              ? [
                  <NumberField assistant={false}
                    key="dbscan-eps"
                    label="DBSCAN eps (× median sample distance)"
                    value={pca.dbscanEpsFactor}
                    onChange={(v) => setPca({ ...pca, dbscanEpsFactor: Math.max(0.001, v) })}
                  />,
                  <NumberField assistant={false}
                    key="dbscan-min-samples"
                    label="DBSCAN Min Samples"
                    value={pca.dbscanMinSamples}
                    onChange={(v) =>
                      setPca({ ...pca, dbscanMinSamples: Math.max(1, Math.min(50, Math.round(v))) })
                    }
                  />,
                ]
              : []),
            ...(showUmap
              ? [
                  <NumberField assistant={false}
                    key="umap-neighbors"
                    label="UMAP Neighbors"
                    value={pca.umapNNeighbors}
                    onChange={(v) =>
                      setPca({ ...pca, umapNNeighbors: Math.max(2, Math.min(200, Math.round(v))) })
                    }
                  />,
                  <NumberField assistant={false}
                    key="umap-min-dist"
                    label="UMAP Min Dist"
                    value={pca.umapMinDist}
                    onChange={(v) => setPca({ ...pca, umapMinDist: Math.max(0, Math.min(1, v)) })}
                  />,
                ]
              : []),
            ...(showTsne
              ? [
                  <NumberField assistant={false}
                    key="tsne-perplexity"
                    label="t-SNE Perplexity"
                    value={pca.tsnePerplexity}
                    onChange={(v) => setPca({ ...pca, tsnePerplexity: Math.max(1, v) })}
                  />,
                  <NumberField assistant={false}
                    key="tsne-learning-rate"
                    label="t-SNE Learning Rate"
                    value={pca.tsneLearningRate}
                    onChange={(v) => setPca({ ...pca, tsneLearningRate: Math.max(10, v) })}
                  />,
                ]
              : []),
            ...(showRandomState
              ? [
                  <NumberField assistant={false}
                    key="random-state"
                    label="Random State"
                    value={pca.randomState}
                    onChange={(v) => setPca({ ...pca, randomState: Math.max(0, Math.round(v)) })}
                  />,
                ]
              : []),
          ]}
          size={
            pca.type === "Interactive" ? null : <SizeRow
              dpi={pca.dpi}
              heightCm={pca.heightCm}
              widthCm={pca.widthCm}
              onDpiChange={(v) => setPca({ ...pca, dpi: v })}
              onHeightChange={(v) => setPca({ ...pca, heightCm: v })}
              onWidthChange={(v) => setPca({ ...pca, widthCm: v })}
            />
          }
        />
        </div>
      );
    }

    if (activeTab === "abundance") {
      const abundanceConditions = ["All Conditions", ...conditionOptions];
      return (
        <OptionsLayout order="toggles-fields-size"
          toggles={[
          ]}
          fields={[
            <SelectField
              key="type"
              label="Type"
              value={abundance.type}
              onChange={(value) => setAbundance({ ...abundance, type: value })}
              options={["Normal", "Interactive"]}
            />,
            <SelectField
              key="condition"
              label="Condition"
              value={abundance.condition}
              onChange={(value) => setAbundance({ ...abundance, condition: value || "All Conditions" })}
              options={abundanceConditions}
            />,
          ]}
          size={
            abundance.type === "Interactive" ? null : <SizeRow
              dpi={abundance.dpi}
              heightCm={abundance.heightCm}
              widthCm={abundance.widthCm}
              onDpiChange={(v) => setAbundance({ ...abundance, dpi: v })}
              onHeightChange={(v) => setAbundance({ ...abundance, heightCm: v })}
              onWidthChange={(v) => setAbundance({ ...abundance, widthCm: v })}
            />
          }
        />
      );
    }

    return (
      <div className="space-y-4">
        {/* Pairwise-complete Pearson: each cell can rest on a different feature set. */}
        <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600" role="note">
          Each correlation uses only the features measured in both samples, so with missing values
          the cells can rest on different sets of features.
        </div>
      <OptionsLayout order="toggles-fields-size"
        toggles={[
          <CheckboxField assistant={false} key="id" label="Toggle IDs" checked={correlation.includeId} onChange={(v) => setCorrelation({ ...correlation, includeId: v })} />,
          <CheckboxField assistant={false} key="full-range" label="Use Full Range" checked={correlation.fullRange} onChange={(v) => setCorrelation({ ...correlation, fullRange: v })} />,
        ]}
        fields={[
          <SelectField
            key="method"
            label="Type"
            value={correlation.method}
            onChange={(value) => setCorrelation({ ...correlation, method: value })}
            options={["Matrix", "Ellipse"]}
          />,
        ]}
        size={
          <SizeRow
            dpi={correlation.dpi}
            heightCm={correlation.heightCm}
            widthCm={correlation.widthCm}
            onDpiChange={(v) => setCorrelation({ ...correlation, dpi: v })}
            onHeightChange={(v) => setCorrelation({ ...correlation, heightCm: v })}
            onWidthChange={(v) => setCorrelation({ ...correlation, widthCm: v })}
          />
        }
      />
      </div>
    );
  }
}

/**
 * A `robust_site_median` phosphoprotein matrix holds ratios to each site's own
 * across-sample median, so its CV is the spread of a ratio, not of an
 * abundance. The plot is still drawn -- the numbers are real, they just do not
 * sit on the same scale as the protein and phosphosite CVs beside them. The
 * warning belongs here, under the figure, never inside the image.
 */
function CentredCvNotice() {
  return (
    <div className="mt-4 rounded-xl border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
      <span className="font-medium">Ratios, not abundances</span> &mdash; this phosphoprotein matrix
      was collapsed with <span className="font-mono">robust_site_median</span>, so its values are
      ratios to each site&rsquo;s own median. This CV is therefore not comparable with the protein-
      or phosphosite-level CVs.
    </div>
  );
}

function PcaFeatureNotice({
  summary,
  dataSource,
}: {
  summary: QcPcaFeatureSummary | null;
  dataSource: string;
}) {
  if (!summary || summary.featuresTotal <= 0) return null;
  const { featuresComplete, featuresUsed, featuresTotal, featuresRequired } = summary;
  const skipped = summary.ellipseSkippedGroups ?? [];
  const fraction = featuresUsed / featuresTotal;
  const missingnessBlocksPca = featuresComplete < featuresRequired;
  const constantFeaturesBlockPca = !missingnessBlocksPca && featuresUsed < featuresRequired;
  const cannotRun = missingnessBlocksPca || constantFeaturesBlockPca;
  // Features with any missing value are dropped before projection, so a low
  // fraction means the plot reflects a small, abundance-biased subset.
  const severe = cannotRun || featuresUsed < 3 || fraction < 0.05;
  const warn = severe || fraction < 0.25;
  const tone = severe
    ? "border-red-300 bg-red-50 text-red-800"
    : warn
      ? "border-amber-300 bg-amber-50 text-amber-800"
      : "border-slate-200 bg-slate-50 text-slate-600";
  return (
    <div className="space-y-2">
      <div className={`rounded-xl border px-3 py-2 text-sm ${tone}`}>
        <span className="font-medium">
          PCA-usable features: {featuresUsed.toLocaleString()} of {featuresTotal.toLocaleString()}
          ({(fraction * 100).toFixed(1)}%)
        </span>
        {missingnessBlocksPca ? (
          <span>
            {" "}
            &mdash; PCA cannot run because only {featuresComplete.toLocaleString()} complete feature
            {featuresComplete === 1 ? " remains" : "s remain"}; the missingness is too high. {dataSource === "imputed"
              ? "Rerun Imputation successfully and then retry with Imputed Data."
              : "Run Imputation, then select Imputed Data here."}
          </span>
        ) : null}
        {constantFeaturesBlockPca ? (
          <span>
            {" "}
            &mdash; PCA cannot run because fewer than {featuresRequired} complete, variable features
            remain after constant features are excluded.
          </span>
        ) : null}
        {warn && !cannotRun ? (
          <span>
            {" "}
            &mdash; features missing in any sample are excluded, so this projection reflects only
            the consistently detected (and therefore more abundant) subset.
            {severe ? " Too few features remain for the plot to be meaningful." : ""}
          </span>
        ) : null}
      </div>
      {summary.dbscan ? (
        <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
          <span className="font-medium">DBSCAN eps used: {summary.dbscan.epsEffective.toPrecision(3)}</span>{" "}
          &mdash; {summary.dbscan.epsFactor} × the median distance between samples in this projection
          ({summary.dbscan.medianSampleDistance.toPrecision(3)}). Samples labelled Noise have fewer than
          the minimum number of neighbours within that radius.
        </div>
      ) : null}
      {summary.smallSampleNotice ? (
        <div className="rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {summary.smallSampleNotice}
        </div>
      ) : null}
      {skipped.length > 0 ? (
        <div className="rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          <span className="font-medium">
            No ellipse for {skipped.length === 1 ? "group" : "groups"} {skipped.join(", ")}
          </span>{" "}
          &mdash; {skipped.length === 1 ? "its" : "their"} points have no spread in one direction
          (they fall on a line, or two samples sit at the same position), so there is no enclosing
          ellipse to fit. The points themselves are unaffected, and the other groups are drawn
          normally.
        </div>
      ) : null}
    </div>
  );
}


function tabTitle(tab: QcTab): string {
  switch (tab) {
    case "coverage":
      return "Coverage Plot";
    case "histogram":
      return "Histogram Intensity";
    case "boxplot":
      return "Boxplot Intensity";
    case "cv":
      return "CV Plot";
    case "pca":
      return "Principal Component Analysis";
    case "abundance":
      return "Abundance Plot";
    case "correlation":
      return "Correlation Plot";
  }
}

function cmToIframeHeight(heightCm: number): number {
  return iframeHeightForPlot(heightCm, { fallbackCm: 10, minPx: 760, paddingPx: 220 });
}
