import { compactTextElement } from "./lib/plotSerialization";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import AppShell from "./components/AppShell";
import TopTabs from "./components/TopTabs";
import ManualEmbed from "./components/ManualEmbed";
import ModuleLoadBoundary from "./components/ModuleLoadBoundary";
import type { AdvancedPlotControlDefaults } from "./components/plots/AdvancedPlotOptions";
import UploadPage from "./features/upload/UploadPage";
import type {
  ComparisonTab,
  CompletenessTab,
  DataTab,
  ExternalTab,
  PhosphoTab,
  PeptideTab,
  QcTab,
  SidebarSection,
  SingleProteinTab,
  SummaryTab,
  StatsTab,
  AdvancedPlotSettings,
} from "./lib/types";
import { useCurrentDatasetsSnapshot } from "./lib/datasetAvailability";
import { IS_AI_MODE, IS_VIEWER_MODE } from "./lib/appMode";
import { downloadRestoreState } from "./lib/api";
import { unsavedAnalysis, warnBeforeUnload } from "./lib/unsavedAnalysis";
import {
  applyCopylotSessionStorageState,
  captureCopylotSessionStorageState,
} from "./lib/restoreUiState";
import {
  clearPersistedSaveStateTarget,
  isPickerAbortError,
  loadPersistedSaveStateTarget,
  openRestoreStateFileWithPicker,
  persistSaveStateTarget,
  saveRestoreStateBlob,
  supportsNativeOpenStatePicker,
  type SaveStateFileHandle,
} from "./lib/saveStateFile";
import { withBasePath } from "./lib/basePath";
import {
  getAdvancedPlotMode,
  getAdvancedPlotSettingsByKey,
  initializeSessionTheme,
  setActiveAdvancedPlotSettings,
  setAdvancedPlotMode,
  setAdvancedPlotSettingsByKey,
} from "./lib/appSettings";

const AdvancedPlotOptions = lazy(() => import("./components/plots/AdvancedPlotOptions"));
const AnalysisPage = lazy(() => import("./features/analysis/AnalysisPage"));
const AnnotationPage = lazy(() => import("./features/metadata/AnnotationPage"));
const AnnotationViewerPage = lazy(() => import("./features/metadata/AnnotationViewerPage"));
const ImputationPage = lazy(() => import("./features/data/ImputationPage"));
const DistributionPage = lazy(() => import("./features/data/DistributionPage"));
const IdTranslatorPage = lazy(() => import("./features/data/IdTranslatorPage"));
const ColorsPage = lazy(() => import("./features/data/ColorsPage"));
const RestorePage = lazy(() => import("./features/data/RestorePage"));
const CompletenessPage = lazy(() => import("./features/completeness/CompletenessPage"));
const QCPipelinePage = lazy(() => import("./features/qc/QCPipelinePage"));
const StatisticalAnalysisPage = lazy(() => import("./features/stats/StatisticalAnalysisPage"));
const PeptideLevelPage = lazy(() => import("./features/peptide/PeptideLevelPage"));
const SingleProteinPage = lazy(() => import("./features/single-protein/SingleProteinPage"));
const PhosphoSpecificPage = lazy(() => import("./features/phospho/PhosphoSpecificPage"));
const KseaPage = lazy(() => import("./features/phospho/KseaPage"));
const ComparisonPipelinePage = lazy(() => import("./features/comparison/ComparisonPipelinePage"));
const PeptideCollapsePage = lazy(() => import("./features/external/PeptideCollapsePage"));
const GONetViewPage = lazy(() => import("./features/external/GONetViewPage"));
const SettingsPage = lazy(() => import("./features/settings/SettingsPage"));
const TablesPage = lazy(() => import("./features/summary/TablesPage"));
const TextPage = lazy(() => import("./features/summary/TextPage"));
const ReportPage = lazy(() => import("./features/summary/ReportPage"));

const dataTabs: { key: DataTab; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "annotation", label: "Annotation" },
  { key: "imputation", label: "Imputation" },
  { key: "distribution", label: "Distribution" },
  { key: "translator", label: "ID Translator" },
  { key: "conditionPalette", label: "Colors" },
  { key: "restore", label: "Restore" },
];

const qcTabs: { key: QcTab; label: string }[] = [
  { key: "coverage", label: "Coverage Plot" },
  { key: "histogram", label: "Histogram Intensity" },
  { key: "boxplot", label: "Boxplot Intensity" },
  { key: "cv", label: "Cov Plot" },
  { key: "pca", label: "Principal Component Analysis" },
  { key: "abundance", label: "Abundance Plot" },
  { key: "correlation", label: "Correlation Plot" },
];

const completenessTabs: { key: CompletenessTab; label: string }[] = [
  { key: "missingPlot", label: "Missing Value Plot" },
  { key: "heatmap", label: "Missing Value Heatmap" },
  { key: "tables", label: "Tables" },
];

const statsTabs: { key: StatsTab; label: string }[] = [
  { key: "volcano", label: "Volcano Plot" },
  { key: "anova", label: "ANOVA" },
  { key: "ora", label: "GO Enrichment (ORA)" },
  { key: "pathwayHeatmap", label: "Pathway Heatmap" },
  { key: "simulation", label: "Simulation" },
];

const peptideTabs: { key: PeptideTab; label: string }[] = [
  { key: "rtPlot", label: "RT Plot" },
  { key: "modification", label: "Modification Plot" },
  { key: "missedCleavage", label: "Missed Cleavage Plot" },
  { key: "sequenceCoverage", label: "Sequence Coverage" },
];

const singleProteinTabs: { key: SingleProteinTab; label: string }[] = [
  { key: "boxplot", label: "Protein Boxplot" },
  { key: "lineplot", label: "Protein Lineplot" },
  { key: "heatmap", label: "Phosphosites on Protein Heatmap" },
];

const phosphoTabs: { key: PhosphoTab; label: string }[] = [
  { key: "phosphositePlot", label: "Phosphosite Plot" },
  { key: "coverage", label: "Phosphosite Coverage Plot" },
  { key: "ksea", label: "KSEA" },
  { key: "distribution", label: "Phosphosite Distribution" },
  { key: "sty", label: "STY Plot" },
  { key: "phosprotRegulation", label: "Phosprot Regulation" },
];

const comparisonTabs: { key: ComparisonTab; label: string }[] = [
  { key: "pearson", label: "Pearson Correlation" },
  { key: "venn", label: "Venn Diagram" },
];

const externalTabs: { key: ExternalTab; label: string }[] = [
  { key: "peptideCollapse", label: "Peptide Collapse" },
  { key: "gonetView", label: "GONetView" },
];

const MATPLOTLIB_DEFAULT_ADVANCED_CONTROLS: AdvancedPlotControlDefaults = {
  axisLineLeft: true,
  axisLineRight: true,
  axisLineBottom: true,
  axisLineTop: true,
  gridLineVisible: false,
  gridLineAxis: "y",
  gridLineStyle: "dashed",
  gridLineWidth: 0.8,
};

const PLOTLY_DEFAULT_ADVANCED_CONTROLS: AdvancedPlotControlDefaults = {
  axisLineLeft: false,
  axisLineRight: false,
  axisLineBottom: false,
  axisLineTop: false,
  gridLineVisible: true,
  gridLineAxis: "both",
  gridLineColor: "#EBF0F8",
  gridLineStyle: "solid",
  gridLineWidth: 1,
};

const NO_AXIS_DEFAULT_ADVANCED_CONTROLS: AdvancedPlotControlDefaults = {
  axisLineLeft: false,
  axisLineRight: false,
  axisLineBottom: false,
  axisLineTop: false,
  gridLineVisible: false,
  gridLineAxis: "y",
  gridLineStyle: "dashed",
  gridLineWidth: 0.8,
};

const LEFT_BOTTOM_AXIS_DEFAULT_ADVANCED_CONTROLS: AdvancedPlotControlDefaults = {
  axisLineLeft: true,
  axisLineRight: false,
  axisLineBottom: true,
  axisLineTop: false,
  gridLineVisible: false,
  gridLineAxis: "y",
  gridLineStyle: "dashed",
  gridLineWidth: 0.8,
};

const BOTH_GRID_DEFAULT_ADVANCED_CONTROLS: AdvancedPlotControlDefaults = {
  ...MATPLOTLIB_DEFAULT_ADVANCED_CONTROLS,
  gridLineVisible: true,
  gridLineAxis: "both",
  gridLineStyle: "solid",
};

const LEFT_BOTTOM_Y_GRID_DEFAULT_ADVANCED_CONTROLS: AdvancedPlotControlDefaults = {
  ...LEFT_BOTTOM_AXIS_DEFAULT_ADVANCED_CONTROLS,
  gridLineVisible: true,
  gridLineAxis: "y",
  gridLineStyle: "solid",
};

const summaryTabs: { key: SummaryTab; label: string }[] = [
  { key: "tables", label: "Tables" },
  { key: "text", label: "Text" },
  { key: "report", label: "Report" },
];

const viewerDataTabs: { key: DataTab; label: string }[] = dataTabs.filter(
  (tab) => tab.key === "upload" || tab.key === "annotation"
);

const allSidebarSections: SidebarSection[] = [
  "data",
  "analysis",
  "completeness",
  "qc",
  "stats",
  "peptide",
  "singleProtein",
  "phospho",
  "comparison",
  "summary",
  "external",
  "settings",
];

type RightPanel = "none" | "list" | "chat";
type SaveStateStatus = {
  tone: "success" | "error";
  message: string;
};

const EMPTY_ADVANCED_PLOT_SETTINGS: AdvancedPlotSettings = {};

function compactAdvancedMap(value: Record<string, string> | undefined): Record<string, string> | undefined {
  const entries = Object.entries(value ?? {})
    .map(([key, val]) => [key.trim(), val.trim()] as const)
    .filter(([key, val]) => key && val);
  return entries.length ? Object.fromEntries(entries) : undefined;
}


function compactAdvancedPlotSettings(settings: AdvancedPlotSettings): AdvancedPlotSettings {
  const titleElement = compactTextElement(settings.titleElement);
  const xLabelElement = compactTextElement(settings.xLabelElement);
  const yLabelElement = compactTextElement(settings.yLabelElement);
  const conditionLabels = compactAdvancedMap(settings.conditionLabels);
  const sampleLabels = compactAdvancedMap(settings.sampleLabels);
  const conditionColors = compactAdvancedMap(settings.conditionColors);
  const referenceLineColor = settings.referenceLineColor?.trim();
  const boxBorderColor = settings.boxBorderColor?.trim();
  const boxMedianColor = settings.boxMedianColor?.trim();
  const boxOutlierColor = settings.boxOutlierColor?.trim();
  const boxOutlierEdgeColor = settings.boxOutlierEdgeColor?.trim();
  const correlationColorMap = settings.correlationColorMap?.trim();
  const backgroundColor = settings.backgroundColor?.trim();
  const plotTheme = settings.plotTheme?.trim();
  const axisLineColor = settings.axisLineColor?.trim();
  const axisLineStyle = settings.axisLineStyle?.trim();
  const gridLineAxis = settings.gridLineAxis?.trim();
  const gridLineColor = settings.gridLineColor?.trim();
  const gridLineStyle = settings.gridLineStyle?.trim();
  const next: AdvancedPlotSettings = {};

  if (titleElement) {
    next.titleElement = titleElement;
    if (titleElement.text) next.title = titleElement.text;
    if (titleElement.size) next.titleSize = titleElement.size;
  }
  if (xLabelElement) {
    next.xLabelElement = xLabelElement;
    if (xLabelElement.text) next.xLabel = xLabelElement.text;
  }
  if (yLabelElement) {
    next.yLabelElement = yLabelElement;
    if (yLabelElement.text) next.yLabel = yLabelElement.text;
  }
  if (settings.tickLabelSize && settings.tickLabelSize > 0) next.tickLabelSize = settings.tickLabelSize;
  if (settings.xTickLabelSize && settings.xTickLabelSize > 0) next.xTickLabelSize = settings.xTickLabelSize;
  if (settings.yTickLabelSize && settings.yTickLabelSize > 0) next.yTickLabelSize = settings.yTickLabelSize;
  if (Number.isFinite(settings.xTickLabelRotation)) next.xTickLabelRotation = settings.xTickLabelRotation;
  if (Number.isFinite(settings.yTickLabelRotation)) next.yTickLabelRotation = settings.yTickLabelRotation;
  if (settings.legendFontSize && settings.legendFontSize > 0) next.legendFontSize = settings.legendFontSize;
  if (settings.legendXOffset) next.legendXOffset = settings.legendXOffset;
  if (settings.legendYOffset) next.legendYOffset = settings.legendYOffset;
  if (referenceLineColor) next.referenceLineColor = referenceLineColor;
  if (boxBorderColor) next.boxBorderColor = boxBorderColor;
  if (boxMedianColor) next.boxMedianColor = boxMedianColor;
  if (boxOutlierColor) next.boxOutlierColor = boxOutlierColor;
  if (boxOutlierEdgeColor) next.boxOutlierEdgeColor = boxOutlierEdgeColor;
  if (settings.boxOutlierSize && settings.boxOutlierSize > 0) next.boxOutlierSize = settings.boxOutlierSize;
  if (correlationColorMap) next.correlationColorMap = correlationColorMap;
  if (backgroundColor) next.backgroundColor = backgroundColor;
  if (typeof settings.transparentBackground === "boolean") next.transparentBackground = settings.transparentBackground;
  if (plotTheme && plotTheme !== "default") next.plotTheme = plotTheme;
  if (typeof settings.axisLineVisible === "boolean") next.axisLineVisible = settings.axisLineVisible;
  if (axisLineColor) next.axisLineColor = axisLineColor;
  if (settings.axisLineWidth && settings.axisLineWidth > 0) next.axisLineWidth = settings.axisLineWidth;
  if (axisLineStyle && axisLineStyle !== "solid") next.axisLineStyle = axisLineStyle;
  if (typeof settings.axisLineTop === "boolean") next.axisLineTop = settings.axisLineTop;
  if (typeof settings.axisLineRight === "boolean") next.axisLineRight = settings.axisLineRight;
  if (typeof settings.axisLineBottom === "boolean") next.axisLineBottom = settings.axisLineBottom;
  if (typeof settings.axisLineLeft === "boolean") next.axisLineLeft = settings.axisLineLeft;
  if (typeof settings.gridLineVisible === "boolean") next.gridLineVisible = settings.gridLineVisible;
  if (gridLineAxis && gridLineAxis !== "y") next.gridLineAxis = gridLineAxis;
  if (gridLineColor) next.gridLineColor = gridLineColor;
  if (settings.gridLineWidth && settings.gridLineWidth > 0) next.gridLineWidth = settings.gridLineWidth;
  if (gridLineStyle && gridLineStyle !== "solid") next.gridLineStyle = gridLineStyle;
  if (conditionLabels) next.conditionLabels = conditionLabels;
  if (sampleLabels) next.sampleLabels = sampleLabels;
  if (conditionColors) next.conditionColors = conditionColors;
  return next;
}

const manualPath = (filename: string) => withBasePath(`/manuals/${filename}`);

export default function App() {
  const {
    datasets,
    loading: datasetsLoading,
    activePackage,
    availablePackages,
    setActivePackage,
    activeMetadataProfile,
    availableMetadataProfiles,
    autoGeneratedMetadataProfiles,
    setMetadataProfile,
  } = useCurrentDatasetsSnapshot();
  const [activeSection, setActiveSection] = useState<SidebarSection>("data");
  const [activeDataTab, setActiveDataTab] = useState<DataTab>("upload");
  const [activeQcTab, setActiveQcTab] = useState<QcTab>("coverage");
  const [activeCompletenessTab, setActiveCompletenessTab] = useState<CompletenessTab>("missingPlot");
  const [activeStatsTab, setActiveStatsTab] = useState<StatsTab>("volcano");
  const [activePeptideTab, setActivePeptideTab] = useState<PeptideTab>("rtPlot");
  const [activeSingleProteinTab, setActiveSingleProteinTab] = useState<SingleProteinTab>("boxplot");
  const [activePhosphoTab, setActivePhosphoTab] = useState<PhosphoTab>("phosphositePlot");
  const [activeComparisonTab, setActiveComparisonTab] = useState<ComparisonTab>("pearson");
  const [activeSummaryTab, setActiveSummaryTab] = useState<SummaryTab>("tables");
  const [activeExternalTab, setActiveExternalTab] = useState<ExternalTab>("peptideCollapse");
  const [advancedModeEnabled, setAdvancedModeEnabled] = useState(() => getAdvancedPlotMode());
  const [advancedByKey, setAdvancedByKey] = useState<Record<string, AdvancedPlotSettings>>(
    () => getAdvancedPlotSettingsByKey()
  );
  const [qcWorkflowScope, setQcWorkflowScope] = useState<string>("");
  const [qcBoxplotMode, setQcBoxplotMode] = useState<string>("");
  const [qcPcaContextMode, setQcPcaContextMode] = useState<string>("");
  const [qcAbundanceContextMode, setQcAbundanceContextMode] = useState<string>("");
  const [qcCoverageContextMode, setQcCoverageContextMode] = useState<string>("");
  const [completenessContextMode, setCompletenessContextMode] = useState<string>("");
  const [statsVolcanoContextMode, setStatsVolcanoContextMode] = useState<string>("");
  const [statsAnovaContextMode, setStatsAnovaContextMode] = useState<string>("");
  const [statsOraContextMode, setStatsOraContextMode] = useState<string>("");
  const [statsPathwayHeatmapContextMode, setStatsPathwayHeatmapContextMode] = useState<string>("");
  const [peptideContextMode, setPeptideContextMode] = useState<string>("");
  const [singleProteinBoxplotContextMode, setSingleProteinBoxplotContextMode] = useState<string>("");
  const [comparisonPearsonContextMode, setComparisonPearsonContextMode] = useState<string>("");
  const [phosphoContextMode, setPhosphoContextMode] = useState<string>("");
  const [rightPanel, setRightPanel] = useState<RightPanel>("none");
  const [switchError, setSwitchError] = useState<string | null>(null);
  const [metadataSwitchTarget, setMetadataSwitchTarget] = useState<string | null>(null);
  const [saveStateHandle, setSaveStateHandle] = useState<SaveStateFileHandle | null>(null);
  const [saveStateFileName, setSaveStateFileName] = useState<string | null>(null);
  const [saveStateStatus, setSaveStateStatus] = useState<SaveStateStatus | null>(null);
  const saveStateStatusTimerRef = useRef<number | null>(null);
  const showDatasetSwitcher = availablePackages.length >= 2;
  const annotationMode = activeSection === "data" && activeDataTab === "annotation";
  const metadataOptions = useMemo(() => {
    if (!annotationMode) return availableMetadataProfiles;
    const auto = new Set(autoGeneratedMetadataProfiles);
    const manualOnly = availableMetadataProfiles.filter((name) => !auto.has(name));
    return manualOnly.length > 0 ? manualOnly : availableMetadataProfiles;
  }, [annotationMode, availableMetadataProfiles, autoGeneratedMetadataProfiles]);
  const showMetadataSwitcher = metadataOptions.length >= 2;
  const showTopSelector = Boolean(activePackage) || showDatasetSwitcher || showMetadataSwitcher;
  const switchMetadataProfile = useCallback(
    async (profileName: string) => {
      const next = profileName.trim();
      if (!next || next === activeMetadataProfile) return;
      setSwitchError(null);
      setMetadataSwitchTarget(next);
      try {
        await setMetadataProfile(next);
      } catch (err) {
        setSwitchError(err instanceof Error ? err.message : "Failed to switch metadata profile");
      } finally {
        setMetadataSwitchTarget((current) => (current === next ? null : current));
      }
    },
    [activeMetadataProfile, setMetadataProfile]
  );
  const activeAdvancedPlotKey = useMemo(() => {
    if (activeSection === "data" && activeDataTab === "distribution") {
      return "data:distribution";
    }
    if (activeSection === "stats") {
      return activeStatsTab === "simulation" ? null : `stats:${activeStatsTab}`;
    }
    if (activeSection === "peptide") return `peptide:${activePeptideTab}`;
    if (activeSection === "singleProtein") return `singleProtein:${activeSingleProteinTab}`;
    if (activeSection === "phospho") return `phospho:${activePhosphoTab}`;
    if (activeSection === "comparison") return `comparison:${activeComparisonTab}`;
    return null;
  }, [
    activeSection,
    activeDataTab,
    activeStatsTab,
    activePeptideTab,
    activeSingleProteinTab,
    activePhosphoTab,
    activeComparisonTab,
  ]);
  const activeAdvancedSettings = activeAdvancedPlotKey
    ? advancedByKey[activeAdvancedPlotKey] ?? EMPTY_ADVANCED_PLOT_SETTINGS
    : EMPTY_ADVANCED_PLOT_SETTINGS;
  const activeAdvancedControlDefaults = useMemo<AdvancedPlotControlDefaults>(() => {
    if (!activeAdvancedPlotKey) return MATPLOTLIB_DEFAULT_ADVANCED_CONTROLS;
    if (
      activeAdvancedPlotKey === "stats:volcano"
    ) {
      return PLOTLY_DEFAULT_ADVANCED_CONTROLS;
    }
    if (activeAdvancedPlotKey === "peptide:rtPlot") {
      const isInteractive = peptideContextMode.toLowerCase().includes("type=interactive");
      return isInteractive ? PLOTLY_DEFAULT_ADVANCED_CONTROLS : MATPLOTLIB_DEFAULT_ADVANCED_CONTROLS;
    }
    if (activeAdvancedPlotKey === "singleProtein:lineplot") {
      return BOTH_GRID_DEFAULT_ADVANCED_CONTROLS;
    }
    if (activeAdvancedPlotKey === "singleProtein:heatmap") {
      return NO_AXIS_DEFAULT_ADVANCED_CONTROLS;
    }
    if (activeAdvancedPlotKey === "phospho:phosphositePlot") {
      return LEFT_BOTTOM_AXIS_DEFAULT_ADVANCED_CONTROLS;
    }
    if (activeAdvancedPlotKey === "phospho:sty") {
      return LEFT_BOTTOM_Y_GRID_DEFAULT_ADVANCED_CONTROLS;
    }
    if (activeAdvancedPlotKey === "phospho:phosprotRegulation") {
      return PLOTLY_DEFAULT_ADVANCED_CONTROLS;
    }
    if (activeAdvancedPlotKey === "comparison:pearson") {
      const isInteractive = comparisonPearsonContextMode.toLowerCase().includes("type=interactive");
      return isInteractive ? PLOTLY_DEFAULT_ADVANCED_CONTROLS : BOTH_GRID_DEFAULT_ADVANCED_CONTROLS;
    }
    if (activeAdvancedPlotKey === "comparison:venn") {
      return NO_AXIS_DEFAULT_ADVANCED_CONTROLS;
    }
    return MATPLOTLIB_DEFAULT_ADVANCED_CONTROLS;
  }, [activeAdvancedPlotKey, comparisonPearsonContextMode, peptideContextMode]);

  useEffect(() => {
    setAdvancedPlotSettingsByKey(advancedByKey);
  }, [advancedByKey]);

  useEffect(() => {
    const refreshAdvancedMode = () => setAdvancedModeEnabled(getAdvancedPlotMode());
    window.addEventListener("copylot:advancedPlotModeChanged", refreshAdvancedMode);
    window.addEventListener("storage", refreshAdvancedMode);
    return () => {
      window.removeEventListener("copylot:advancedPlotModeChanged", refreshAdvancedMode);
      window.removeEventListener("storage", refreshAdvancedMode);
    };
  }, []);

  useEffect(() => {
    if (!advancedModeEnabled || !activeAdvancedPlotKey) {
      setActiveAdvancedPlotSettings(null);
      return;
    }
    const timeout = window.setTimeout(() => {
      setActiveAdvancedPlotSettings(compactAdvancedPlotSettings(activeAdvancedSettings));
    }, 350);
    return () => window.clearTimeout(timeout);
  }, [advancedModeEnabled, activeAdvancedPlotKey, activeAdvancedSettings]);

  useEffect(() => {
    if (!annotationMode) return;
    if (metadataOptions.includes(activeMetadataProfile)) return;
    if (metadataSwitchTarget) return;
    const fallback = metadataOptions[0];
    if (!fallback) return;
    void switchMetadataProfile(fallback);
  }, [
    annotationMode,
    metadataOptions,
    activeMetadataProfile,
    metadataSwitchTarget,
    switchMetadataProfile,
  ]);

  useEffect(() => {
    document.title = "Proteomics CoPYlot";
    initializeSessionTheme();
  }, []);

  useEffect(() => {
    loadPersistedSaveStateTarget().then((target) => {
      if (target.handle) {
        setSaveStateHandle(target.handle);
      }
      if (target.fileName) {
        setSaveStateFileName(target.fileName);
      }
    }).catch(() => {
      // Ignore persisted-handle load failures.
    });
  }, []);

  useEffect(() => {
    return () => {
      if (saveStateStatusTimerRef.current != null) {
        window.clearTimeout(saveStateStatusTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (activeSection !== "analysis" && rightPanel === "list") {
      setRightPanel("none");
    }
  }, [activeSection, rightPanel]);

  useEffect(() => {
    if (!IS_AI_MODE && rightPanel === "chat") {
      setRightPanel("none");
    }
  }, [rightPanel]);

  useEffect(() => {
    if (activeSection === "qc") return;
    setQcWorkflowScope("");
  }, [activeSection]);

  useEffect(() => {
    if (activeSection === "qc" && activeQcTab === "boxplot") return;
    setQcBoxplotMode("");
  }, [activeSection, activeQcTab]);

  useEffect(() => {
    if (activeSection === "qc" && activeQcTab === "pca") return;
    setQcPcaContextMode("");
  }, [activeSection, activeQcTab]);

  useEffect(() => {
    if (
      activeSection === "completeness" &&
      (activeCompletenessTab === "missingPlot" || activeCompletenessTab === "heatmap" || activeCompletenessTab === "tables")
    ) return;
    setCompletenessContextMode("");
  }, [activeSection, activeCompletenessTab]);

  useEffect(() => {
    if (activeSection === "stats" && activeStatsTab === "volcano") return;
    setStatsVolcanoContextMode("");
  }, [activeSection, activeStatsTab]);

  useEffect(() => {
    if (activeSection === "stats" && activeStatsTab === "anova") return;
    setStatsAnovaContextMode("");
  }, [activeSection, activeStatsTab]);

  useEffect(() => {
    if (activeSection === "stats" && activeStatsTab === "ora") return;
    setStatsOraContextMode("");
  }, [activeSection, activeStatsTab]);

  useEffect(() => {
    if (activeSection === "stats" && activeStatsTab === "pathwayHeatmap") return;
    setStatsPathwayHeatmapContextMode("");
  }, [activeSection, activeStatsTab]);

  useEffect(() => {
    if (activeSection === "peptide") return;
    setPeptideContextMode("");
  }, [activeSection]);

  useEffect(() => {
    if (
      activeSection === "singleProtein" &&
      (activeSingleProteinTab === "boxplot" || activeSingleProteinTab === "lineplot" || activeSingleProteinTab === "heatmap")
    ) return;
    setSingleProteinBoxplotContextMode("");
  }, [activeSection, activeSingleProteinTab]);

  useEffect(() => {
    if (activeSection === "comparison" && (activeComparisonTab === "pearson" || activeComparisonTab === "venn")) return;
    setComparisonPearsonContextMode("");
  }, [activeSection, activeComparisonTab]);

  useEffect(() => {
    if (
      activeSection === "phospho" &&
      (
        activePhosphoTab === "phosphositePlot" ||
        activePhosphoTab === "coverage" ||
        activePhosphoTab === "distribution" ||
        activePhosphoTab === "sty" ||
        activePhosphoTab === "phosprotRegulation"
      )
    ) return;
    setPhosphoContextMode("");
  }, [activeSection, activePhosphoTab]);

  const visibleDataTabs = useMemo(
    () => (IS_VIEWER_MODE ? viewerDataTabs : dataTabs),
    []
  );
  const visibleStatsTabs = useMemo(
    () =>
      IS_VIEWER_MODE
        ? statsTabs.filter((tab) => tab.key !== "simulation")
        : statsTabs,
    []
  );
  const visiblePeptideTabs = useMemo(
    () =>
      IS_VIEWER_MODE
        ? peptideTabs.filter((tab) => tab.key !== "sequenceCoverage")
        : peptideTabs,
    []
  );
  const visibleSingleProteinTabs = useMemo(
    () => {
      if (!IS_VIEWER_MODE) return singleProteinTabs;
      if (datasetsLoading || datasets === null) return singleProteinTabs;
      return datasets.phospho
        ? singleProteinTabs
        : singleProteinTabs.filter((tab) => tab.key !== "heatmap");
    },
    [datasets, datasetsLoading]
  );
  const visibleExternalTabs = useMemo(
    () =>
      IS_VIEWER_MODE
        ? externalTabs.filter((tab) => tab.key === "gonetView")
        : externalTabs,
    []
  );
  const visibleSummaryTabs = useMemo(
    () =>
      IS_VIEWER_MODE
        ? summaryTabs.filter((tab) => tab.key === "tables")
        : summaryTabs,
    []
  );
  const visiblePhosphoTabs = useMemo(
    () =>
      IS_VIEWER_MODE
        ? phosphoTabs.filter((tab) => tab.key !== "ksea")
        : phosphoTabs,
    []
  );

  const visibleSections = useMemo<SidebarSection[]>(() => {
    if (!IS_VIEWER_MODE) return allSidebarSections;

    const sections: SidebarSection[] = [
      "data",
      "analysis",
      "completeness",
      "qc",
      "stats",
      "singleProtein",
    ];
    if (datasets?.peptide) sections.push("peptide");
    const hasPhosphoWorkflow = Boolean(datasets?.phospho || datasets?.phosprot);
    // Keep phospho-specific visible while initial dataset loading is still unresolved,
    // then apply strict data-based visibility once snapshot is available.
    if (hasPhosphoWorkflow || datasetsLoading || datasets === null) sections.push("phospho");
    sections.push("comparison", "summary", "external", "settings");
    return sections;
  }, [datasets, datasetsLoading]);

  useEffect(() => {
    if (!visibleSections.includes(activeSection)) {
      setActiveSection(visibleSections[0] ?? "data");
    }
  }, [activeSection, visibleSections]);

  useEffect(() => {
    if (!visibleDataTabs.some((tab) => tab.key === activeDataTab)) {
      setActiveDataTab(visibleDataTabs[0]?.key ?? "upload");
    }
  }, [activeDataTab, visibleDataTabs]);

  useEffect(() => {
    if (!visibleStatsTabs.some((tab) => tab.key === activeStatsTab)) {
      setActiveStatsTab(visibleStatsTabs[0]?.key ?? "volcano");
    }
  }, [activeStatsTab, visibleStatsTabs]);

  useEffect(() => {
    if (!visiblePeptideTabs.some((tab) => tab.key === activePeptideTab)) {
      setActivePeptideTab(visiblePeptideTabs[0]?.key ?? "rtPlot");
    }
  }, [activePeptideTab, visiblePeptideTabs]);

  useEffect(() => {
    if (!visibleSingleProteinTabs.some((tab) => tab.key === activeSingleProteinTab)) {
      setActiveSingleProteinTab(visibleSingleProteinTabs[0]?.key ?? "boxplot");
    }
  }, [activeSingleProteinTab, visibleSingleProteinTabs]);

  useEffect(() => {
    if (!visibleExternalTabs.some((tab) => tab.key === activeExternalTab)) {
      setActiveExternalTab(visibleExternalTabs[0]?.key ?? "gonetView");
    }
  }, [activeExternalTab, visibleExternalTabs]);

  useEffect(() => {
    if (!visibleSummaryTabs.some((tab) => tab.key === activeSummaryTab)) {
      setActiveSummaryTab(visibleSummaryTabs[0]?.key ?? "tables");
    }
  }, [activeSummaryTab, visibleSummaryTabs]);

  useEffect(() => {
    if (!visiblePhosphoTabs.some((tab) => tab.key === activePhosphoTab)) {
      setActivePhosphoTab(visiblePhosphoTabs[0]?.key ?? "phosphositePlot");
    }
  }, [activePhosphoTab, visiblePhosphoTabs]);

  const topManual = useMemo(() => {
    if (activeSection === "data") {
      return null;
    }
    if (activeSection === "qc") {
      if (activeQcTab === "coverage") return { title: "Coverage Plot Manual", path: manualPath("CoveragePlotManual.pdf") };
      if (activeQcTab === "histogram") return { title: "Histogram Intensity Manual", path: manualPath("HistogramIntensityManual.pdf") };
      if (activeQcTab === "boxplot") return { title: "Boxplot Intensity Manual", path: manualPath("BoxplotIntensityManual.pdf") };
      if (activeQcTab === "cv") return { title: "Coefficient of Variation Plot Manual", path: manualPath("CoefficientofVariationPlotManual.pdf") };
      if (activeQcTab === "pca") return { title: "Principal Component Analysis Plot Manual", path: manualPath("PrincipalComponentAnalysisPlotManual.pdf") };
      if (activeQcTab === "abundance") return { title: "Abundance Plot Manual", path: manualPath("AbundancePlotManual.pdf") };
      if (activeQcTab === "correlation") return { title: "Correlation Plot Manual", path: manualPath("CorrelationPlotManual.pdf") };
      return null;
    }
    if (activeSection === "completeness") {
      if (activeCompletenessTab === "missingPlot") return { title: "Missing Value Plot Manual", path: manualPath("MissingValuePlotManual.pdf") };
      if (activeCompletenessTab === "heatmap") return { title: "Missing Value Heatmap Manual", path: manualPath("MissingValueHeatmapManual.pdf") };
      if (activeCompletenessTab === "tables") return { title: "Missing Value Tables Manual", path: manualPath("MissingValueTablesManual.pdf") };
      return null;
    }
    if (activeSection === "stats") {
      if (activeStatsTab === "volcano") {
        return { title: "Volcano Plot Manual", path: manualPath("VolcanoPlotManual.pdf") };
      }
      return null;
    }
    if (activeSection === "singleProtein") {
      if (activeSingleProteinTab === "boxplot") return { title: "Protein Boxplot Manual", path: manualPath("ProteinBoxplotManual.pdf") };
      if (activeSingleProteinTab === "lineplot") return { title: "Protein Lineplot Manual", path: manualPath("ProteinLineplotManual.pdf") };
      return null;
    }
    if (activeSection === "phospho") {
      if (activePhosphoTab === "phosphositePlot") return { title: "Phosphosite Plot Manual", path: manualPath("PhossitePlotManual.pdf") };
      if (activePhosphoTab === "coverage") return { title: "Phosphosite Coverage Plot Manual", path: manualPath("PhossiteCoveragePlotManual.pdf") };
      if (activePhosphoTab === "distribution") return { title: "Phosphosite Distribution Manual", path: manualPath("PhossiteDistributionPlotManual.pdf") };
      if (activePhosphoTab === "phosprotRegulation") return { title: "Phosphoprotein Regulation Manual", path: manualPath("PhosprotRegulationPlotManual.pdf") };
      return null;
    }
    if (activeSection === "comparison") {
      if (activeComparisonTab === "pearson") return { title: "Pearson Correlation Plot Manual", path: manualPath("PearsonCorrelationPlotManual.pdf") };
      if (activeComparisonTab === "venn") return { title: "Venn Diagram Manual", path: manualPath("VennDiagramManual.pdf") };
      return null;
    }
    return null;
  }, [
    activeSection,
    activeQcTab,
    activeCompletenessTab,
    activeStatsTab,
    activeSingleProteinTab,
    activePhosphoTab,
    activeComparisonTab,
  ]);

  const topManualButton = useMemo(
    () => topManual ? (
      <ManualEmbed pdfPath={topManual.path} title={topManual.title} buttonLabel="Manual" />
    ) : null,
    [topManual]
  );

  const activeModuleKey = useMemo(() => {
    if (activeSection === "data") return `data.${activeDataTab}`;
    if (activeSection === "analysis") return "analysis.canvas";
    if (activeSection === "completeness") return `completeness.${activeCompletenessTab}`;
    if (activeSection === "qc") return `qc.${activeQcTab}`;
    if (activeSection === "stats") return `stats.${activeStatsTab}`;
    if (activeSection === "peptide") return `peptide.${activePeptideTab}`;
    if (activeSection === "singleProtein") return `singleProtein.${activeSingleProteinTab}`;
    if (activeSection === "phospho") return `phospho.${activePhosphoTab}`;
    if (activeSection === "comparison") return `comparison.${activeComparisonTab}`;
    if (activeSection === "summary") return `summary.${activeSummaryTab}`;
    if (activeSection === "external") return `external.${activeExternalTab}`;
    return `${activeSection}.unknown`;
  }, [
    activeSection,
    activeDataTab,
    activeCompletenessTab,
    activeQcTab,
    activeStatsTab,
    activePeptideTab,
    activeSingleProteinTab,
    activePhosphoTab,
    activeComparisonTab,
    activeSummaryTab,
    activeExternalTab,
  ]);

  const activeWorkflowScope = useMemo(() => {
    if (activeSection === "qc") {
      const scoped = qcWorkflowScope.trim().toLowerCase();
      if (scoped) return scoped;
    }
    if (activeSection === "phospho") {
      return activePhosphoTab === "phosprotRegulation" ? "phosphoprotein" : "phosphosite";
    }
    if (activeSection === "peptide") {
      return "peptide";
    }
    if (activeSection === "singleProtein") {
      return activeSingleProteinTab === "heatmap" ? "phosphosite" : "protein";
    }
    if (activeSection === "comparison" && (activeComparisonTab === "pearson" || activeComparisonTab === "venn")) {
      const mode = comparisonPearsonContextMode.trim().toLowerCase();
      if (mode.includes("kind=phospho")) return "phosphosite";
      if (mode.includes("kind=phosprot")) return "phosphoprotein";
      return "protein";
    }

    const hasProtein = Boolean(datasets?.protein);
    const hasPhospho = Boolean(datasets?.phospho);
    const hasPhosprot = Boolean(datasets?.phosprot);
    if (hasProtein && !hasPhospho && !hasPhosprot) return "protein";
    if (!hasProtein && hasPhospho && !hasPhosprot) return "phosphosite";
    if (!hasProtein && !hasPhospho && hasPhosprot) return "phosphoprotein";

    return "";
  }, [
    activeSection,
    activePhosphoTab,
    activeSingleProteinTab,
    activeComparisonTab,
    comparisonPearsonContextMode,
    datasets,
    qcWorkflowScope,
  ]);

  const activeContextMode = useMemo(() => {
    if (activeSection === "stats" && activeStatsTab === "volcano") {
      return statsVolcanoContextMode.trim();
    }
    if (activeSection === "stats" && activeStatsTab === "anova") {
      return statsAnovaContextMode.trim();
    }
    if (activeSection === "stats" && activeStatsTab === "ora") {
      return statsOraContextMode.trim();
    }
    if (activeSection === "stats" && activeStatsTab === "pathwayHeatmap") {
      return statsPathwayHeatmapContextMode.trim();
    }
    if (
      activeSection === "completeness" &&
      (activeCompletenessTab === "missingPlot" || activeCompletenessTab === "heatmap" || activeCompletenessTab === "tables")
    ) {
      return completenessContextMode.trim();
    }
    if (activeSection === "qc" && activeQcTab === "boxplot") {
      return qcBoxplotMode.trim();
    }
    if (activeSection === "qc" && activeQcTab === "pca") {
      return qcPcaContextMode.trim();
    }
    if (activeSection === "qc" && activeQcTab === "abundance") {
      return qcAbundanceContextMode.trim();
    }
    if (activeSection === "qc" && activeQcTab === "coverage") {
      return qcCoverageContextMode.trim();
    }
    if (
      activeSection === "peptide" &&
      (
        activePeptideTab === "rtPlot" ||
        activePeptideTab === "modification" ||
        activePeptideTab === "missedCleavage" ||
        activePeptideTab === "sequenceCoverage"
      )
    ) {
      return peptideContextMode.trim();
    }
    if (
      activeSection === "singleProtein" &&
      (activeSingleProteinTab === "boxplot" || activeSingleProteinTab === "lineplot" || activeSingleProteinTab === "heatmap")
    ) {
      return singleProteinBoxplotContextMode.trim();
    }
    if (activeSection === "comparison" && (activeComparisonTab === "pearson" || activeComparisonTab === "venn")) {
      return comparisonPearsonContextMode.trim();
    }
    if (
      activeSection === "phospho" &&
      (
        activePhosphoTab === "phosphositePlot" ||
        activePhosphoTab === "coverage" ||
        activePhosphoTab === "distribution" ||
        activePhosphoTab === "sty" ||
        activePhosphoTab === "phosprotRegulation"
      )
    ) {
      return phosphoContextMode.trim();
    }
    return "";
  }, [
    activeSection,
    activeStatsTab,
    activeCompletenessTab,
    activeQcTab,
    activePeptideTab,
    activeSingleProteinTab,
    activeComparisonTab,
    activePhosphoTab,
    statsVolcanoContextMode,
    statsAnovaContextMode,
    statsOraContextMode,
    statsPathwayHeatmapContextMode,
    completenessContextMode,
    qcBoxplotMode,
    qcPcaContextMode,
    qcAbundanceContextMode,
    qcCoverageContextMode,
    peptideContextMode,
    singleProteinBoxplotContextMode,
    comparisonPearsonContextMode,
    phosphoContextMode,
  ]);

  const selectorBar = showTopSelector ? (
    <div className="border-b border-slate-200 bg-white px-4 py-2 sm:px-6">
      <div className="flex flex-wrap items-center gap-3">
        {!showDatasetSwitcher ? <span className="min-w-0 break-all text-xs text-slate-600">Dataset: <strong>{activePackage}</strong></span> : null}
        {!showMetadataSwitcher ? <span className="min-w-0 break-all text-xs text-slate-600">Metadata: <strong>{activeMetadataProfile}</strong></span> : null}
        {showDatasetSwitcher ? (
          <>
            <label htmlFor="active-dataset-package" className="text-xs font-semibold uppercase tracking-wide text-slate-600">
              Dataset
            </label>
            <select
              value={activePackage}
              id="active-dataset-package"
              onChange={(event) => {
                const next = event.target.value;
                setSwitchError(null);
                setActivePackage(next).catch((err) => {
                  setSwitchError(err instanceof Error ? err.message : "Failed to switch dataset package");
                });
              }}
              className="min-w-44 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
            >
              {availablePackages.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </>
        ) : null}
        {showMetadataSwitcher ? (
          <>
            <label htmlFor="active-metadata-profile" className="text-xs font-semibold uppercase tracking-wide text-slate-600">
              Metadata
            </label>
            <select
              value={metadataSwitchTarget ?? activeMetadataProfile}
              id="active-metadata-profile"
              onChange={(event) => {
                void switchMetadataProfile(event.target.value);
              }}
              disabled={metadataSwitchTarget !== null}
              className="min-w-44 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
            >
              {metadataOptions.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </>
        ) : null}
        {switchError ? <div className="text-sm text-red-600">{switchError}</div> : null}
      </div>
    </div>
  ) : null;

  const topBar = useMemo(() => {
    if (activeSection === "data") {
      return (
        <TopTabs
          tabs={visibleDataTabs}
          activeTab={activeDataTab}
          onChange={setActiveDataTab}
          rightContent={topManualButton}
        />
      );
    }

    if (activeSection === "analysis") {
      return null;
    }

    if (activeSection === "qc") {
      return (
        <TopTabs
          tabs={qcTabs}
          activeTab={activeQcTab}
          onChange={setActiveQcTab}
          rightContent={topManualButton}
        />
      );
    }

    if (activeSection === "completeness") {
      return (
        <TopTabs
          tabs={completenessTabs}
          activeTab={activeCompletenessTab}
          onChange={setActiveCompletenessTab}
          rightContent={topManualButton}
        />
      );
    }

    if (activeSection === "stats") {
      return (
        <TopTabs
          tabs={visibleStatsTabs}
          activeTab={activeStatsTab}
          onChange={setActiveStatsTab}
          rightContent={topManualButton}
        />
      );
    }

    if (activeSection === "peptide") {
      return (
        <TopTabs
          tabs={visiblePeptideTabs}
          activeTab={activePeptideTab}
          onChange={setActivePeptideTab}
          rightContent={topManualButton}
        />
      );
    }

    if (activeSection === "singleProtein") {
      return (
        <TopTabs
          tabs={visibleSingleProteinTabs}
          activeTab={activeSingleProteinTab}
          onChange={setActiveSingleProteinTab}
          rightContent={topManualButton}
        />
      );
    }

    if (activeSection === "phospho") {
      return (
        <TopTabs
          tabs={visiblePhosphoTabs}
          activeTab={activePhosphoTab}
          onChange={setActivePhosphoTab}
          rightContent={topManualButton}
        />
      );
    }

    if (activeSection === "comparison") {
      return (
        <TopTabs
          tabs={comparisonTabs}
          activeTab={activeComparisonTab}
          onChange={setActiveComparisonTab}
          rightContent={topManualButton}
        />
      );
    }

    if (activeSection === "summary") {
      return (
        <TopTabs
          tabs={visibleSummaryTabs}
          activeTab={activeSummaryTab}
          onChange={setActiveSummaryTab}
          rightContent={topManualButton}
        />
      );
    }

    if (activeSection === "external") {
      return (
        <TopTabs
          tabs={visibleExternalTabs}
          activeTab={activeExternalTab}
          onChange={setActiveExternalTab}
          rightContent={topManualButton}
        />
      );
    }

    return null;
  }, [
    activeSection,
    activeDataTab,
    activeQcTab,
    activeCompletenessTab,
    activeStatsTab,
    activePeptideTab,
    activeSingleProteinTab,
    activePhosphoTab,
    activeComparisonTab,
    activeSummaryTab,
    activeExternalTab,
    topManualButton,
    visibleDataTabs,
    visibleStatsTabs,
    visiblePeptideTabs,
    visibleSingleProteinTabs,
    visibleExternalTabs,
    visibleSummaryTabs,
    visiblePhosphoTabs,
  ]);

  const combinedTopBar = selectorBar || topBar ? (
    <>
      {selectorBar}
      {topBar}
    </>
  ) : null;

  function showSaveStateMessage(tone: SaveStateStatus["tone"], message: string) {
    setSaveStateStatus({ tone, message });
    if (saveStateStatusTimerRef.current != null) {
      window.clearTimeout(saveStateStatusTimerRef.current);
    }
    saveStateStatusTimerRef.current = window.setTimeout(() => {
      setSaveStateStatus(null);
      saveStateStatusTimerRef.current = null;
    }, 2800);
  }

  function buildUiStateSnapshot(): Record<string, unknown> {
    return {
      version: 2,
      app: {
        activeSection,
        activeDataTab,
        activeQcTab,
        activeCompletenessTab,
        activeStatsTab,
        activePeptideTab,
        activeSingleProteinTab,
        activePhosphoTab,
        activeComparisonTab,
        activeSummaryTab,
        activeExternalTab,
        rightPanel,
      },
      advancedPlot: {
        enabled: advancedModeEnabled,
        settingsByKey: advancedByKey,
      },
      sessionStorageState: captureCopylotSessionStorageState(),
    };
  }

  const uiSnapshotRef = useRef(buildUiStateSnapshot);
  uiSnapshotRef.current = buildUiStateSnapshot;
  useEffect(() => {
    if (IS_VIEWER_MODE) return;
    // Capture defaults before the first user edit, not before child pages have
    // finished persisting their initial defaults/dataset scope.
    const initializeBaseline = () => unsavedAnalysis.initialize(uiSnapshotRef.current());
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      initializeBaseline();
      warnBeforeUnload(event, unsavedAnalysis.isDirty(uiSnapshotRef.current()));
    };
    window.addEventListener("pointerdown", initializeBaseline, { capture: true, once: true });
    window.addEventListener("keydown", initializeBaseline, { capture: true, once: true });
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("pointerdown", initializeBaseline, true);
      window.removeEventListener("keydown", initializeBaseline, true);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, []);

  function applyUiStateSnapshot(payload: Record<string, unknown>, matchesSavedFile = false) {
    if (matchesSavedFile) unsavedAnalysis.markSaved(unsavedAnalysis.capture(payload));
    const appState = payload?.app;
    const advancedPlotState = payload?.advancedPlot;
    const localStorageState = payload?.localStorageState ?? payload?.reportLocalStorage;
    const sessionStorageState = payload?.sessionStorageState;
    applyCopylotSessionStorageState({
      ...(localStorageState && typeof localStorageState === "object" ? localStorageState : {}),
      ...(sessionStorageState && typeof sessionStorageState === "object" ? sessionStorageState : {}),
    });
    const restoredAdvancedMode = getAdvancedPlotMode();
    const restoredAdvancedSettings = getAdvancedPlotSettingsByKey();
    setAdvancedModeEnabled(restoredAdvancedMode);
    setAdvancedByKey(restoredAdvancedSettings);
    if (!restoredAdvancedMode) {
      setActiveAdvancedPlotSettings(null);
    }
    if (advancedPlotState && typeof advancedPlotState === "object") {
      const advanced = advancedPlotState as Record<string, unknown>;
      const enabled = Boolean(advanced.enabled);
      const settingsByKey =
        advanced.settingsByKey && typeof advanced.settingsByKey === "object" && !Array.isArray(advanced.settingsByKey)
          ? (advanced.settingsByKey as Record<string, AdvancedPlotSettings>)
          : {};
      setAdvancedPlotSettingsByKey(settingsByKey);
      setAdvancedPlotMode(enabled);
      setAdvancedModeEnabled(enabled);
      setAdvancedByKey(settingsByKey);
      if (!enabled) {
        setActiveAdvancedPlotSettings(null);
      }
    } else {
      setAdvancedPlotSettingsByKey(restoredAdvancedSettings);
      setAdvancedPlotMode(restoredAdvancedMode);
    }
    const next = appState && typeof appState === "object"
      ? (appState as Record<string, unknown>)
      : {};

    const nextSection = String(next.activeSection ?? "data").trim() as SidebarSection;
    if (allSidebarSections.includes(nextSection)) {
      setActiveSection(nextSection);
    }

    const nextData = String(next.activeDataTab ?? "upload").trim() as DataTab;
    if (dataTabs.some((item) => item.key === nextData)) {
      setActiveDataTab(nextData);
    }
    const nextQc = String(next.activeQcTab ?? "coverage").trim() as QcTab;
    if (qcTabs.some((item) => item.key === nextQc)) {
      setActiveQcTab(nextQc);
    }
    const nextCompleteness = String(next.activeCompletenessTab ?? "missingPlot").trim() as CompletenessTab;
    if (completenessTabs.some((item) => item.key === nextCompleteness)) {
      setActiveCompletenessTab(nextCompleteness);
    }
    const nextStats = String(next.activeStatsTab ?? "volcano").trim() as StatsTab;
    if (statsTabs.some((item) => item.key === nextStats)) {
      setActiveStatsTab(nextStats);
    }
    const nextPeptide = String(next.activePeptideTab ?? "rtPlot").trim() as PeptideTab;
    if (peptideTabs.some((item) => item.key === nextPeptide)) {
      setActivePeptideTab(nextPeptide);
    }
    const nextSingle = String(next.activeSingleProteinTab ?? "boxplot").trim() as SingleProteinTab;
    if (singleProteinTabs.some((item) => item.key === nextSingle)) {
      setActiveSingleProteinTab(nextSingle);
    }
    const nextPhospho = String(next.activePhosphoTab ?? "phosphositePlot").trim() as PhosphoTab;
    if (phosphoTabs.some((item) => item.key === nextPhospho)) {
      setActivePhosphoTab(nextPhospho);
    }
    const nextComparison = String(next.activeComparisonTab ?? "pearson").trim() as ComparisonTab;
    if (comparisonTabs.some((item) => item.key === nextComparison)) {
      setActiveComparisonTab(nextComparison);
    }
    const nextSummary = String(next.activeSummaryTab ?? "tables").trim() as SummaryTab;
    if (summaryTabs.some((item) => item.key === nextSummary)) {
      setActiveSummaryTab(nextSummary);
    }
    const nextExternal = String(next.activeExternalTab ?? "peptideCollapse").trim() as ExternalTab;
    if (externalTabs.some((item) => item.key === nextExternal)) {
      setActiveExternalTab(nextExternal);
    }
    const nextRightPanel = String(next.rightPanel ?? "none").trim() as RightPanel;
    if (nextRightPanel === "none" || nextRightPanel === "list" || nextRightPanel === "chat") {
      setRightPanel(nextRightPanel);
    }
  }

  async function writeSaveState(forcePicker = false): Promise<void> {
    const uiState = buildUiStateSnapshot();
    const checkpoint = unsavedAnalysis.capture(uiState);
    const { blob, filename } = await downloadRestoreState(uiState);
    const result = await saveRestoreStateBlob({
      blob,
      suggestedName: saveStateFileName || filename,
      existingHandle: forcePicker ? null : saveStateHandle,
      forcePicker,
    });
    setSaveStateHandle(result.handle);
    setSaveStateFileName(result.fileName);
    if (result.method === "handle" || window.confirm(
      `Confirm that ${result.fileName} finished downloading and is available on your computer. Cancel keeps the unsaved-changes warning active.`
    )) unsavedAnalysis.markSaved(checkpoint);
    if (result.handle) {
      await persistSaveStateTarget(result.handle);
    } else if (forcePicker) {
      await clearPersistedSaveStateTarget();
    }
    showSaveStateMessage(
      "success",
      result.method === "handle"
        ? `Save state written to ${result.fileName}`
        : `Save state downloaded as ${result.fileName}`
    );
  }

  async function handleQuickSave(forcePicker = false): Promise<boolean> {
    try {
      await writeSaveState(forcePicker);
      return true;
    } catch (error) {
      if (isPickerAbortError(error)) return false;
      const message = error instanceof Error ? error.message : "Failed to save state.";
      showSaveStateMessage("error", message);
      throw error;
    }
  }

  async function handlePortableSave(): Promise<boolean> {
    try {
      const uiState = buildUiStateSnapshot();
      const checkpoint = unsavedAnalysis.capture(uiState);
      const { blob, filename } = await downloadRestoreState(uiState, {
        portable: true,
      });
      const result = await saveRestoreStateBlob({
        blob,
        suggestedName: filename,
        existingHandle: null,
        forcePicker: true,
      });
      if (result.method === "handle" || window.confirm(
        `Confirm that ${result.fileName} finished downloading and is available on your computer. Cancel keeps the unsaved-changes warning active.`
      )) unsavedAnalysis.markSaved(checkpoint);
      showSaveStateMessage(
        "success",
        `Portable save state written to ${result.fileName}; local dataset paths were omitted.`
      );
      return true;
    } catch (error) {
      if (isPickerAbortError(error)) return false;
      const message = error instanceof Error ? error.message : "Failed to save portable state.";
      showSaveStateMessage("error", message);
      throw error;
    }
  }
  const handleQuickSaveRef = useRef(handleQuickSave);
  handleQuickSaveRef.current = handleQuickSave;

  async function handleOpenRestoreStateFile(): Promise<File | null> {
    try {
      const opened = await openRestoreStateFileWithPicker();
      setSaveStateHandle(opened.handle);
      setSaveStateFileName(opened.file.name);
      await persistSaveStateTarget(opened.handle);
      showSaveStateMessage("success", `Opened save state ${opened.file.name}`);
      return opened.file;
    } catch (error) {
      if (isPickerAbortError(error)) return null;
      const message = error instanceof Error ? error.message : "Failed to open save state.";
      showSaveStateMessage("error", message);
      throw error;
    }
  }

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.repeat) return;
      if (event.altKey) return;
      if (!(event.ctrlKey || event.metaKey)) return;
      if (String(event.key || "").toLowerCase() !== "s") return;
      event.preventDefault();
      void handleQuickSaveRef.current(false).catch(() => {
        // Status is already surfaced through the shared save-state banner.
      });
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function renderContent() {
    if (activeSection === "completeness") {
      return (
        <CompletenessPage
          activeTab={activeCompletenessTab}
          onContextModeChange={setCompletenessContextMode}
        />
      );
    }

    if (activeSection === "qc") {
      return (
        <QCPipelinePage
          activeTab={activeQcTab}
          onWorkflowScopeChange={setQcWorkflowScope}
          onBoxplotModeChange={setQcBoxplotMode}
          onPcaContextModeChange={setQcPcaContextMode}
          onAbundanceContextModeChange={setQcAbundanceContextMode}
          onCoverageContextModeChange={setQcCoverageContextMode}
        />
      );
    }

    if (activeSection === "stats") {
      const effectiveStatsTab = IS_VIEWER_MODE && activeStatsTab === "simulation"
        ? "volcano"
        : activeStatsTab;
      const onContextModeChange = effectiveStatsTab === "volcano"
        ? setStatsVolcanoContextMode
        : effectiveStatsTab === "anova"
          ? setStatsAnovaContextMode
          : effectiveStatsTab === "ora"
            ? setStatsOraContextMode
            : effectiveStatsTab === "pathwayHeatmap"
              ? setStatsPathwayHeatmapContextMode
              : undefined;
      return (
        <StatisticalAnalysisPage
          activeTab={effectiveStatsTab}
          onContextModeChange={onContextModeChange}
          advancedPlotOptions={activeAdvancedPlotOptionsPanel}
        />
      );
    }

    if (activeSection === "peptide") {
      const effectivePeptideTab = IS_VIEWER_MODE && activePeptideTab === "sequenceCoverage"
        ? "rtPlot"
        : activePeptideTab;
      return (
        <PeptideLevelPage
          activeTab={effectivePeptideTab}
          onContextModeChange={setPeptideContextMode}
          advancedPlotOptions={activeAdvancedPlotOptionsPanel}
        />
      );
    }

    if (activeSection === "singleProtein") {
      const effectiveSingleProteinTab = IS_VIEWER_MODE &&
        activeSingleProteinTab === "heatmap" &&
        !datasets?.phospho &&
        !datasetsLoading
        ? "boxplot"
        : activeSingleProteinTab;
      return (
        <SingleProteinPage
          activeTab={effectiveSingleProteinTab}
          onContextModeChange={setSingleProteinBoxplotContextMode}
          advancedPlotOptions={activeAdvancedPlotOptionsPanel}
        />
      );
    }

    if (activeSection === "phospho") {
      if (activePhosphoTab === "ksea") {
        if (IS_VIEWER_MODE) {
          return <PhosphoSpecificPage activeTab="phosphositePlot" advancedPlotOptions={activeAdvancedPlotOptionsPanel} />;
        }
        return <KseaPage advancedPlotOptions={activeAdvancedPlotOptionsPanel} />;
      }
      return (
        <PhosphoSpecificPage
          activeTab={activePhosphoTab}
          onContextModeChange={setPhosphoContextMode}
          advancedPlotOptions={activeAdvancedPlotOptionsPanel}
        />
      );
    }

    if (activeSection === "comparison") {
      return (
        <ComparisonPipelinePage
          activeTab={activeComparisonTab}
          onContextModeChange={setComparisonPearsonContextMode}
          advancedPlotOptions={activeAdvancedPlotOptionsPanel}
        />
      );
    }

    if (activeSection === "summary") {
      if (IS_VIEWER_MODE) {
        return <TablesPage />;
      }

      if (activeSummaryTab === "tables") {
        return <TablesPage />;
      }

      if (activeSummaryTab === "text") {
        return <TextPage />;
      }

      return <ReportPage />;
    }

    if (activeSection === "external") {
      if (activeExternalTab === "peptideCollapse") {
        if (IS_VIEWER_MODE) {
          return <GONetViewPage />;
        }
        return <PeptideCollapsePage />;
      }
      return <GONetViewPage />;
    }

    if (activeSection === "settings") {
      return <SettingsPage />;
    }

    if (activeSection === "data") {
      if (activeDataTab === "upload") {
        return <UploadPage readOnly={IS_VIEWER_MODE} />;
      }

      if (activeDataTab === "annotation") {
        return IS_VIEWER_MODE ? <AnnotationViewerPage /> : <AnnotationPage />;
      }

      if (activeDataTab === "imputation") {
        return <ImputationPage />;
      }

      if (activeDataTab === "distribution") {
        return <DistributionPage advancedPlotOptions={activeAdvancedPlotOptionsPanel} />;
      }

      if (activeDataTab === "translator") {
        return <IdTranslatorPage />;
      }

      if (activeDataTab === "conditionPalette") {
        return <ColorsPage />;
      }

      if (activeDataTab === "restore") {
        return (
          <RestorePage
            onApplyUiState={applyUiStateSnapshot}
            onQuickSave={() => handleQuickSave(false)}
            onQuickSaveAs={() => handleQuickSave(true)}
            onPortableSave={handlePortableSave}
            onOpenStateFile={supportsNativeOpenStatePicker() ? handleOpenRestoreStateFile : null}
            currentSaveFileName={saveStateFileName}
          />
        );
      }
    }

    if (activeSection === "analysis") {
      return (
        <AnalysisPage
          rightPanel={rightPanel}
          onRightPanelChange={setRightPanel}
          aiEnabled={IS_AI_MODE}
        />
      );
    }

    return (
      <div className="rounded-2xl border border-dashed border-slate-300 bg-white p-12 text-center">
        <div className="text-lg font-semibold text-slate-900">
          {sectionTitle(activeSection)}
        </div>
        <div className="mt-2 text-sm text-slate-500">
          This module is not built yet.
        </div>
      </div>
    );
  }

  const activeAdvancedPlotOptionsPanel = advancedModeEnabled && activeAdvancedPlotKey ? (
    <AdvancedPlotOptions
      key={activeAdvancedPlotKey}
      value={activeAdvancedSettings}
      controlDefaults={activeAdvancedControlDefaults}
      onChange={(next) => {
        if (advancedModeEnabled) {
          setActiveAdvancedPlotSettings(compactAdvancedPlotSettings(next));
        }
        setAdvancedByKey((prev) => ({ ...prev, [activeAdvancedPlotKey]: next }));
      }}
    />
  ) : null;

  return (
    <AppShell
      activeSection={activeSection}
      onSectionChange={setActiveSection}
      sections={visibleSections}
      topBar={combinedTopBar}
      activeModuleKey={activeModuleKey}
      activeWorkflowScope={activeWorkflowScope}
      activeContextMode={activeContextMode}
      aiEnabled={IS_AI_MODE}
      rightPanel={rightPanel}
      onRightPanelChange={setRightPanel}
    >
      {saveStateStatus ? (
        <div
          className={[
            "fixed bottom-4 right-4 z-50 rounded-xl border px-4 py-3 text-sm shadow-lg",
            saveStateStatus.tone === "error"
              ? "border-red-200 bg-red-50 text-red-700"
              : "border-sky-200 bg-sky-50 text-sky-800",
          ].join(" ")}
        >
          {saveStateStatus.message}
        </div>
      ) : null}
      <div
        className="space-y-6"
        key={`${activePackage}:${activeMetadataProfile}:${activeSection}`}
      >
        <ModuleLoadBoundary
          key={activeModuleKey}
          onReturnToUpload={() => {
            setActiveDataTab("upload");
            setActiveSection("data");
          }}
        >
          <Suspense fallback={<ModuleLoadingFallback />}>
            {renderContent()}
          </Suspense>
        </ModuleLoadBoundary>
      </div>
    </AppShell>
  );
}

function ModuleLoadingFallback() {
  return (
    <div
      className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm"
      role="status"
      aria-live="polite"
    >
      <div className="mx-auto h-6 w-6 animate-spin rounded-full border-2 border-slate-300 border-t-slate-800" />
      <div className="mt-3 text-sm font-medium text-slate-700">Loading module…</div>
    </div>
  );
}

function sectionTitle(section: SidebarSection): string {
  switch (section) {
    case "data":
      return "Data";
    case "analysis":
      return "Analysis";
    case "qc":
      return "QC Pipeline";
    case "completeness":
      return "Completeness";
    case "stats":
      return "Statistical Analysis";
    case "peptide":
      return "Peptide Level";
    case "singleProtein":
      return "Single Protein";
    case "phospho":
      return "Phospho-specific";
    case "comparison":
      return "Comparison";
    case "summary":
      return "Summary";
    case "external":
      return "External Tools";
    case "settings":
      return "Settings";
  }
}
