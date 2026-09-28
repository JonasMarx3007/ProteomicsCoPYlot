import { compactAdvancedPlotSettings } from "./lib/plotSerialization";
import { CONTEXT_SLOTS, activeContextSlot, contextText, keepOnly, withContextMode, type ContextModes, type ContextSlot } from "./lib/contextModes";
import type { ContextMode } from "./lib/types";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import AppShell from "./components/AppShell";
import { AssistantAppearanceMount, AssistantSurface } from "./components/AssistantFields";
import { usePlotLabels } from "./lib/usePlotLabels";
import TopTabs from "./components/TopTabs";
import ManualEmbed from "./components/ManualEmbed";
import ModuleLoadBoundary from "./components/ModuleLoadBoundary";
import type {
  AdvancedPlotControlDefaults,
  AdvancedPlotVisibleControls,
} from "./components/plots/AdvancedPlotOptions";
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
  MATPLOTLIB_BOTH_GRID_CONTROLS,
  MATPLOTLIB_CONTROLS,
  MATPLOTLIB_LEFT_BOTTOM_CONTROLS,
  MATPLOTLIB_LEFT_BOTTOM_Y_GRID_CONTROLS,
  MATPLOTLIB_NO_FRAME_CONTROLS,
  PLOTLY_DEFAULT_TEMPLATE_CONTROLS,
  PLOTLY_WHITE_TEMPLATE_CONTROLS,
} from "./lib/plotControlDefaults";
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
  { key: "simulation", label: "Replicate & Variance Projection" },
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
  // What each view reports about its selections, keyed by the view. Only the
  // view on screen keeps an entry (see the effect beside `activeContextSlot`).
  const [contextModes, setContextModes] = useState<ContextModes>({});
  const reportContextMode = useMemo(
    () => Object.fromEntries(CONTEXT_SLOTS.map((slot) => [
      slot,
      (mode: ContextMode | null) => setContextModes((current) => withContextMode(current, slot, mode)),
    ])) as Record<ContextSlot, (mode: ContextMode | null) => void>,
    []
  );
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
  const showTopSelector = showDatasetSwitcher || showMetadataSwitcher;
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
    if (activeSection === "peptide") {
      // Sequence coverage is an HTML coverage map and a text download, not a
      // figure, so there is nothing for the plot panel to style.
      return activePeptideTab === "sequenceCoverage" ? null : `peptide:${activePeptideTab}`;
    }
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
  // What the frame and grid controls show untouched: the plot as each renderer
  // actually draws it. See lib/plotControlDefaults.ts for where each value
  // comes from.
  const activeAdvancedControlDefaults = useMemo<AdvancedPlotControlDefaults>(() => {
    if (!activeAdvancedPlotKey) return MATPLOTLIB_CONTROLS;
    switch (activeAdvancedPlotKey) {
      case "stats:volcano": {
        // Two renderers, two natives: the static figure keeps only its left and
        // bottom spines, the interactive one is Plotly's default template.
        const isInteractive = contextText(contextModes["stats:volcano"], "type") !== "normal";
        return isInteractive ? PLOTLY_DEFAULT_TEMPLATE_CONTROLS : MATPLOTLIB_LEFT_BOTTOM_CONTROLS;
      }
      case "peptide:rtPlot": {
        const isInteractive = contextText(contextModes.peptide, "type") === "interactive";
        return isInteractive ? PLOTLY_WHITE_TEMPLATE_CONTROLS : MATPLOTLIB_CONTROLS;
      }
      case "comparison:pearson": {
        const isInteractive = contextText(contextModes.comparison, "type") === "interactive";
        return isInteractive ? PLOTLY_WHITE_TEMPLATE_CONTROLS : MATPLOTLIB_BOTH_GRID_CONTROLS;
      }
      case "phospho:phosprotRegulation":
        return PLOTLY_WHITE_TEMPLATE_CONTROLS;
      case "singleProtein:lineplot":
        return MATPLOTLIB_BOTH_GRID_CONTROLS;
      case "singleProtein:heatmap":
      case "comparison:venn":
        return MATPLOTLIB_NO_FRAME_CONTROLS;
      case "phospho:phosphositePlot":
        return MATPLOTLIB_LEFT_BOTTOM_CONTROLS;
      case "phospho:sty":
        return MATPLOTLIB_LEFT_BOTTOM_Y_GRID_CONTROLS;
      default:
        return MATPLOTLIB_CONTROLS;
    }
  }, [activeAdvancedPlotKey, contextModes]);

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

  // The active plot's settings apply whether the panel is open or not: the
  // mode only decides whether the panel is shown.
  useEffect(() => {
    if (!activeAdvancedPlotKey) {
      setActiveAdvancedPlotSettings(null);
      return;
    }
    const timeout = window.setTimeout(() => {
      setActiveAdvancedPlotSettings(compactAdvancedPlotSettings(activeAdvancedSettings));
    }, 350);
    return () => window.clearTimeout(timeout);
  }, [activeAdvancedPlotKey, activeAdvancedSettings]);

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
      const kind = contextText(contextModes.comparison, "kind");
      if (kind === "phospho") return "phosphosite";
      if (kind === "phosprot") return "phosphoprotein";
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
    contextModes,
    datasets,
    qcWorkflowScope,
  ]);

  // The viewer has no simulation panel; its statistics page shows the volcano there.
  const effectiveStatsTab = IS_VIEWER_MODE && activeStatsTab === "simulation" ? "volcano" : activeStatsTab;
  const activeSlot = activeContextSlot({
    section: activeSection, dataTab: activeDataTab, qcTab: activeQcTab, statsTab: effectiveStatsTab,
    completenessTab: activeCompletenessTab, peptideTab: activePeptideTab,
    singleProteinTab: activeSingleProteinTab, comparisonTab: activeComparisonTab, phosphoTab: activePhosphoTab,
  });
  // A view's selections belong to it while it is on screen. Leaving drops them,
  // so coming back never shows the last visit's selections before the page has
  // reported its current ones.
  useEffect(() => {
    setContextModes((current) => keepOnly(current, activeSlot));
  }, [activeSlot]);
  const activeContextMode = activeSlot ? contextModes[activeSlot] ?? null : null;

  const selectorBar = showTopSelector ? (
    <div className="border-b border-slate-200 bg-white px-4 py-2 sm:px-6">
      <div className="flex flex-wrap items-center gap-3">
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
    const localStorageState = payload?.localStorageState;
    const sessionStorageState = payload?.sessionStorageState;
    applyCopylotSessionStorageState({
      ...(localStorageState && typeof localStorageState === "object" ? localStorageState : {}),
      ...(sessionStorageState && typeof sessionStorageState === "object" ? sessionStorageState : {}),
    });
    const restoredAdvancedMode = getAdvancedPlotMode();
    const restoredAdvancedSettings = getAdvancedPlotSettingsByKey();
    setAdvancedModeEnabled(restoredAdvancedMode);
    setAdvancedByKey(restoredAdvancedSettings);
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
      // `event.code` is the physical key, so these fire the same on a QWERTZ or
      // AZERTY keyboard, where `event.key` for the same key is a different
      // letter. Shift is part of the identity of a shortcut, not a modifier to
      // ignore: Ctrl+Shift+S is the browser's own, and taking it silently is
      // how a user loses a screenshot they meant to take.
      // Quick save is an analysis-mode act: it exports the whole session, which
      // a viewer neither needs nor should be able to take. The advanced plot
      // toggle below stays, so a collaborator can style a publication-ready
      // figure from a published project.
      if (event.code === "KeyS" && !event.shiftKey && !IS_VIEWER_MODE) {
        event.preventDefault();
        void handleQuickSaveRef.current(false).catch(() => {
          // Status is already surfaced through the shared save-state banner.
        });
        return;
      }
      // E, not A: Ctrl/Cmd+Shift+A is Chrome's tab search, and a shortcut the
      // browser answers first is a shortcut this app does not have.
      if (event.code === "KeyE" && event.shiftKey) {
        event.preventDefault();
        // Same switch as Settings > Advanced plot options: the setter
        // broadcasts, so every page listening picks the change up at once.
        setAdvancedPlotMode(!getAdvancedPlotMode());
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function renderContent() {
    if (activeSection === "completeness") {
      return (
        <CompletenessPage
          activeTab={activeCompletenessTab}
          onContextModeChange={reportContextMode.completeness}
        />
      );
    }

    if (activeSection === "qc") {
      return (
        <QCPipelinePage
          activeTab={activeQcTab}
          onWorkflowScopeChange={setQcWorkflowScope}
          onBoxplotContextModeChange={reportContextMode["qc:boxplot"]}
          onPcaContextModeChange={reportContextMode["qc:pca"]}
          onAbundanceContextModeChange={reportContextMode["qc:abundance"]}
          onCoverageContextModeChange={reportContextMode["qc:coverage"]}
        />
      );
    }

    if (activeSection === "stats") {
      const onContextModeChange = reportContextMode[`stats:${effectiveStatsTab}`];
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
          onContextModeChange={reportContextMode.peptide}
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
          onContextModeChange={reportContextMode.singleProtein}
          advancedPlotOptions={activeAdvancedPlotOptionsPanel}
        />
      );
    }

    if (activeSection === "phospho") {
      if (activePhosphoTab === "ksea") {
        if (IS_VIEWER_MODE) {
          return <PhosphoSpecificPage activeTab="phosphositePlot" advancedPlotOptions={activeAdvancedPlotOptionsPanel} />;
        }
        return <KseaPage onContextModeChange={reportContextMode["phospho:ksea"]} advancedPlotOptions={activeAdvancedPlotOptionsPanel} />;
      }
      return (
        <PhosphoSpecificPage
          activeTab={activePhosphoTab}
          onContextModeChange={reportContextMode.phospho}
          advancedPlotOptions={activeAdvancedPlotOptionsPanel}
        />
      );
    }

    if (activeSection === "comparison") {
      return (
        <ComparisonPipelinePage
          activeTab={activeComparisonTab}
          onContextModeChange={reportContextMode.comparison}
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
        return <DistributionPage onContextModeChange={reportContextMode["data:distribution"]} advancedPlotOptions={activeAdvancedPlotOptionsPanel} />;
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
          onContextModeChange={reportContextMode.analysis}
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

  // Which marker controls a plot gets, by what it actually draws. A plot with
  // one class of dot gets one size; the volcano gets three, because its three
  // classes are read differently; the single-protein boxplot gets both its
  // jittered data points and its outlier fliers, which are separate marks that
  // used to share no control at all.
  const activeAdvancedVisibleControls = useMemo<AdvancedPlotVisibleControls>(() => {
    switch (activeAdvancedPlotKey) {
      // A card is shown when the plot's renderer reads the keys it writes.
      // `conditionLabels`, `sampleLabels`, `conditionColors`, `legendControls`,
      // `backgroundControls` and `axisLineControls` default to shown, so a plot
      // that does not use them has to say so -- otherwise the panel offers, for
      // example, a legend card on a Venn diagram that draws no legend, and
      // sample-name rows on a figure with no samples on it. Checked against the
      // renderers in backend/app/services on 2026-09-17.
      case "stats:volcano":
        return {
          volcanoMarkers: true,
          referenceLineColor: true,
          // Both renderers build their title and fold-change axis label
          // through `_volcano_condition_texts`, so a rename reaches them (the
          // sign convention is still `comparison_contrast`'s).
          conditionLabels: true,
          sampleLabels: false,
          conditionColors: false,
        };
      case "singleProtein:boxplot":
        return {
          boxplotStyle: true,
          boxplotOutliers: true,
          boxplotPoints: true,
          // The jittered points are drawn one condition at a time.
          conditionMarkers: true,
          sampleLabels: false,
        };
      case "singleProtein:lineplot":
        // `single_protein_lineplot_plot` draws `marker="o"` on every line and
        // reads none of the marker keys, and its x axis is the sample list from
        // the annotation, which no condition rename passes through -- the
        // renaming there is the boxplot's, not this plot's.
        return { conditionLabels: false, sampleLabels: false, conditionColors: false };
      case "comparison:pearson":
        return {
          markerStyle: true,
          // Both renderers draw the regression fit under this setting (the
          // static PNG since 2026-09-25), so the card applies to either type.
          referenceLineColor: true,
          legendControls: false,
          conditionLabels: false,
          sampleLabels: false,
          conditionColors: false,
        };
      case "comparison:venn":
        return {
          vennColors: true,
          legendControls: false,
          conditionLabels: false,
          sampleLabels: false,
          conditionColors: false,
        };
      case "data:distribution":
      case "peptide:rtPlot":
        return {
          markerStyle: true,
          // The Q-Q fit and the retention-time identity line.
          referenceLineColor: true,
          legendControls: false,
          conditionLabels: false,
          sampleLabels: false,
          conditionColors: false,
        };
      case "phospho:ksea":
        return {
          markerStyle: true,
          // `ksea_plot_png` draws the two fold-change thresholds and the
          // p-value line.
          referenceLineColor: true,
          // It draws one scatter per significance class, each handed its own
          // colour, and a colour passed by the plot wins over `markerColor`.
          markerColor: false,
          conditionLabels: false,
          sampleLabels: false,
          conditionColors: false,
        };
      case "phospho:phosprotRegulation":
        // The tab is `phosprotRegulation` (lib/types.ts PhosphoTab), so the old
        // "phospho:regulation" label never matched: the phosphoprotein
        // regulation plot showed no Points card while its renderer reads
        // markerSize, markerAlpha and the outline keys.
        return {
          markerStyle: true,
          // Both renderers colour the points from `color_val` through a colour
          // scale and pass `use_color=False`, so a dot colour is read and
          // thrown away. Neither draws a threshold line over the figure.
          markerColor: false,
          conditionLabels: false,
          sampleLabels: false,
          conditionColors: false,
        };
      case "singleProtein:heatmap":
        return {
          correlationGradient: true,
          legendControls: false,
          conditionColors: false,
        };
      case "stats:pathwayHeatmap":
        return {
          correlationGradient: true,
          legendControls: false,
          sampleLabels: false,
          conditionColors: false,
        };
      case "phospho:coverage":
        // `phospho_coverage_png` prints no number on any bar, in either mode.
        return { phosphoClassColors: true, sampleLabels: false };
      case "phospho:phosphositePlot":
      case "phospho:distribution":
        return {
          barColor: true,
          legendControls: false,
          conditionLabels: false,
          sampleLabels: false,
          conditionColors: false,
          // The phosphosite plot clears its x ticks, so tick styling has
          // nothing to style.
          tickControls: activeAdvancedPlotKey !== "phospho:phosphositePlot",
        };
      case "peptide:missedCleavage":
        // The only one of the two that writes on its bars: the percentage of
        // sequences with at least one missed cleavage, at `advanced_label_size`.
        return {
          valueLabels: true,
          conditionLabels: false,
          sampleLabels: false,
          conditionColors: false,
        };
      case "peptide:modification":
        // `peptide_modification_plot` draws its grouped bars and stops.
        return {
          conditionLabels: false,
          sampleLabels: false,
          conditionColors: false,
        };
      case "stats:anova":
        // The cluster heatmaps name their rows when "Show feature names" is on;
        // the Row labels card styles them and is only there while they are.
        return {
          rowLabels: contextModes["stats:anova"]?.showRowLabels === true,
        };
      case "stats:ora":
        return {
          legendControls: false,
          conditionLabels: false,
          sampleLabels: false,
          conditionColors: false,
        };
      case "phospho:sty":
        // `phospho_sty_png` draws S, T and Y each in its own fixed colour and
        // never reads `barColor`; one bar colour would have to overwrite three.
        return {
          legendControls: false,
          conditionLabels: false,
          sampleLabels: false,
          conditionColors: false,
        };
      default:
        return {};
    }
  }, [activeAdvancedPlotKey, contextModes]);

  const plotLabels = usePlotLabels(activeWorkflowScope, activeContextMode, Boolean(activeAdvancedPlotKey));
  const activeAdvancedPlotOptionsPanel = activeAdvancedPlotKey ? (
    <AssistantAppearanceMount visible={advancedModeEnabled}>
    <AdvancedPlotOptions
      key={activeAdvancedPlotKey}
      value={activeAdvancedSettings}
      controlDefaults={activeAdvancedControlDefaults}
      conditionOptions={plotLabels?.conditions}
      sampleOptions={plotLabels?.samples}
      sampleDisplayLabels={plotLabels?.sampleLabels}
      visibleControls={activeAdvancedVisibleControls}
      onChange={(next) => {
        setActiveAdvancedPlotSettings(compactAdvancedPlotSettings(next));
        setAdvancedByKey((prev) => ({ ...prev, [activeAdvancedPlotKey]: next }));
      }}
    />
    </AssistantAppearanceMount>
  ) : null;

  const assistantTabs: [SidebarSection, { key: string; label: string }[], (key: string) => void][] = [
    ["data", visibleDataTabs, key => setActiveDataTab(key as DataTab)],
    ["qc", qcTabs, key => setActiveQcTab(key as QcTab)],
    ["completeness", completenessTabs, key => setActiveCompletenessTab(key as CompletenessTab)],
    ["stats", visibleStatsTabs, key => setActiveStatsTab(key as StatsTab)],
    ["peptide", visiblePeptideTabs, key => setActivePeptideTab(key as PeptideTab)],
    ["singleProtein", visibleSingleProteinTabs, key => setActiveSingleProteinTab(key as SingleProteinTab)],
    ["phospho", visiblePhosphoTabs, key => setActivePhosphoTab(key as PhosphoTab)],
    ["comparison", comparisonTabs, key => setActiveComparisonTab(key as ComparisonTab)],
    ["summary", visibleSummaryTabs, key => setActiveSummaryTab(key as SummaryTab)],
    ["external", visibleExternalTabs, key => setActiveExternalTab(key as ExternalTab)],
  ];
  const assistantDestinations = Object.fromEntries(assistantTabs
    .filter(([section]) => visibleSections.includes(section))
    .flatMap(([section, tabs]) => tabs.map(tab => [`${section}.${tab.key}`, `${sectionTitle(section)} / ${tab.label}`])));
  for (const section of visibleSections.filter(section => !assistantTabs.some(([key]) => key === section))) {
    assistantDestinations[`${section}.${section === "analysis" ? "canvas" : "unknown"}`] = sectionTitle(section);
  }

  function assistantNavigate(destination: string) {
    if (!(destination in assistantDestinations)) throw new Error("This tab is unavailable.");
    const [section, tab] = destination.split(".");
    const entry = assistantTabs.find(([key]) => key === section);
    entry?.[2](tab);
    setActiveSection(section as SidebarSection);
  }

  return (
    <AppShell
      activeSection={activeSection}
      onSectionChange={setActiveSection}
      sections={visibleSections}
      topBar={combinedTopBar}
      activeModuleKey={activeModuleKey}
      activeWorkflowScope={activeWorkflowScope}
      activeContextMode={activeContextMode}
      assistantDestinations={assistantDestinations}
      onAssistantNavigate={assistantNavigate}
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
            <AssistantSurface module={activeModuleKey} enabled={IS_AI_MODE && (["qc", "completeness", "stats", "peptide", "singleProtein", "phospho", "comparison", "analysis"].includes(activeSection) || activeModuleKey === "data.distribution")}>
              {renderContent()}
            </AssistantSurface>
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
