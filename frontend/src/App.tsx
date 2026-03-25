import { useEffect, useMemo, useState } from "react";
import AppShell from "./components/AppShell";
import TopTabs from "./components/TopTabs";
import ManualEmbed from "./components/ManualEmbed";
import UploadPage from "./features/upload/UploadPage";
import AnnotationPage from "./features/metadata/AnnotationPage";
import AnnotationViewerPage from "./features/metadata/AnnotationViewerPage";
import ImputationPage from "./features/data/ImputationPage";
import DistributionPage from "./features/data/DistributionPage";
import VerificationPage from "./features/data/VerificationPage";
import IdTranslatorPage from "./features/data/IdTranslatorPage";
import ColorsPage from "./features/data/ColorsPage";
import MissingValuePlotPage from "./features/completeness/MissingValuePlotPage";
import MissingValueHeatmapPage from "./features/completeness/MissingValueHeatmapPage";
import CompletenessTablesPage from "./features/completeness/CompletenessTablesPage";
import CoveragePlotPage from "./features/qc/CoveragePlotPage";
import HistogramIntensityPage from "./features/qc/HistogramIntensityPage";
import BoxplotIntensityPage from "./features/qc/BoxplotIntensityPage";
import CovPlotPage from "./features/qc/CovPlotPage";
import PrincipalComponentAnalysisPage from "./features/qc/PrincipalComponentAnalysisPage";
import AbundancePlotPage from "./features/qc/AbundancePlotPage";
import CorrelationPlotPage from "./features/qc/CorrelationPlotPage";
import VolcanoPlotPage from "./features/stats/VolcanoPlotPage";
import VolcanoPlotControlPage from "./features/stats/VolcanoPlotControlPage";
import GseaPage from "./features/stats/GseaPage";
import PathwayHeatmapPage from "./features/stats/PathwayHeatmapPage";
import SimulationPage from "./features/stats/SimulationPage";
import RtPlotPage from "./features/peptide/RtPlotPage";
import ModificationPlotPage from "./features/peptide/ModificationPlotPage";
import MissedCleavagePlotPage from "./features/peptide/MissedCleavagePlotPage";
import SequenceCoveragePage from "./features/peptide/SequenceCoveragePage";
import ProteinBoxplotPage from "./features/single-protein/ProteinBoxplotPage";
import ProteinLineplotPage from "./features/single-protein/ProteinLineplotPage";
import PhosphositesOnProteinHeatmapPage from "./features/single-protein/PhosphositesOnProteinHeatmapPage";
import PhosphositePlotPage from "./features/phospho/PhosphositePlotPage";
import PhosphositeCoveragePage from "./features/phospho/PhosphositeCoveragePage";
import PhosphositeDistributionPage from "./features/phospho/PhosphositeDistributionPage";
import StyPlotPage from "./features/phospho/StyPlotPage";
import KseaPage from "./features/phospho/KseaPage";
import PhosprotRegulationPage from "./features/phospho/PhosprotRegulationPage";
import PearsonCorrelationPage from "./features/comparison/PearsonCorrelationPage";
import VennDiagramPage from "./features/comparison/VennDiagramPage";
import PeptideCollapsePage from "./features/external/PeptideCollapsePage";
import TablesPage from "./features/summary/TablesPage";
import TextPage from "./features/summary/TextPage";
import ReportPage from "./features/summary/ReportPage";
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
} from "./lib/types";
import { useCurrentDatasetsSnapshot } from "./lib/datasetAvailability";
import { IS_VIEWER_MODE } from "./lib/appMode";

const dataTabs: { key: DataTab; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "annotation", label: "Annotation" },
  { key: "imputation", label: "Imputation" },
  { key: "distribution", label: "Distribution" },
  { key: "verification", label: "Verification" },
  { key: "translator", label: "ID Translator" },
  { key: "conditionPalette", label: "Colors" },
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
  { key: "volcanoControl", label: "Volcano Plot Control" },
  { key: "gsea", label: "GSEA" },
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
  { key: "peptideCollapse", label: "Peptide Collapse Function" },
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
  "completeness",
  "qc",
  "stats",
  "peptide",
  "singleProtein",
  "phospho",
  "comparison",
  "summary",
  "external",
];

export default function App() {
  const { datasets, loading: datasetsLoading } = useCurrentDatasetsSnapshot();
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

  useEffect(() => {
    document.title = "Proteomics CoPYlot";
  }, []);

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
      "completeness",
      "qc",
      "stats",
    ];
    if (datasets?.peptide) sections.push("peptide");
    const hasPhosphoWorkflow = Boolean(datasets?.phospho || datasets?.phosprot);
    // Keep phospho-specific visible while initial dataset loading is still unresolved,
    // then apply strict data-based visibility once snapshot is available.
    if (hasPhosphoWorkflow || datasetsLoading || datasets === null) sections.push("phospho");
    sections.push("comparison", "summary");
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
      if (activeDataTab === "verification") {
        return { title: "Data Information Manual", path: "/manuals/DataInfoManual.pdf" };
      }
      return null;
    }
    if (activeSection === "qc") {
      if (activeQcTab === "coverage") return { title: "Coverage Plot Manual", path: "/manuals/CoveragePlotManual.pdf" };
      if (activeQcTab === "histogram") return { title: "Histogram Intensity Manual", path: "/manuals/HistogramIntensityManual.pdf" };
      if (activeQcTab === "boxplot") return { title: "Boxplot Intensity Manual", path: "/manuals/BoxplotIntensityManual.pdf" };
      if (activeQcTab === "cv") return { title: "Coefficient of Variation Plot Manual", path: "/manuals/CoefficientofVariationPlotManual.pdf" };
      if (activeQcTab === "pca") return { title: "Principal Component Analysis Plot Manual", path: "/manuals/PrincipalComponentAnalysisPlotManual.pdf" };
      if (activeQcTab === "abundance") return { title: "Abundance Plot Manual", path: "/manuals/AbundancePlotManual.pdf" };
      if (activeQcTab === "correlation") return { title: "Correlation Plot Manual", path: "/manuals/CorrelationPlotManual.pdf" };
      return null;
    }
    if (activeSection === "completeness") {
      if (activeCompletenessTab === "missingPlot") return { title: "Missing Value Plot Manual", path: "/manuals/MissingValuePlotManual.pdf" };
      if (activeCompletenessTab === "heatmap") return { title: "Missing Value Heatmap Manual", path: "/manuals/MissingValueHeatmapManual.pdf" };
      if (activeCompletenessTab === "tables") return { title: "Missing Value Tables Manual", path: "/manuals/MissingValueTablesManual.pdf" };
      return null;
    }
    if (activeSection === "stats") {
      if (activeStatsTab === "volcano" || activeStatsTab === "volcanoControl") {
        return { title: "Volcano Plot Manual", path: "/manuals/VolcanoPlotManual.pdf" };
      }
      return null;
    }
    if (activeSection === "singleProtein") {
      if (activeSingleProteinTab === "boxplot") return { title: "Protein Boxplot Manual", path: "/manuals/ProteinBoxplotManual.pdf" };
      if (activeSingleProteinTab === "lineplot") return { title: "Protein Lineplot Manual", path: "/manuals/ProteinLineplotManual.pdf" };
      return null;
    }
    if (activeSection === "phospho") {
      if (activePhosphoTab === "phosphositePlot") return { title: "Phosphosite Plot Manual", path: "/manuals/PhossitePlotManual.pdf" };
      if (activePhosphoTab === "coverage") return { title: "Phosphosite Coverage Plot Manual", path: "/manuals/PhossiteCoveragePlotManual.pdf" };
      if (activePhosphoTab === "distribution") return { title: "Phosphosite Distribution Manual", path: "/manuals/PhossiteDistributionPlotManual.pdf" };
      if (activePhosphoTab === "phosprotRegulation") return { title: "Phosphoprotein Regulation Manual", path: "/manuals/PhosprotRegulationPlotManual.pdf" };
      return null;
    }
    if (activeSection === "comparison") {
      if (activeComparisonTab === "pearson") return { title: "Pearson Correlation Plot Manual", path: "/manuals/PearsonCorrelationPlotManual.pdf" };
      if (activeComparisonTab === "venn") return { title: "Venn Diagram Manual", path: "/manuals/VennDiagramManual.pdf" };
      return null;
    }
    return null;
  }, [
    activeSection,
    activeDataTab,
    activeQcTab,
    activeCompletenessTab,
    activeStatsTab,
    activeSingleProteinTab,
    activePhosphoTab,
    activeComparisonTab,
  ]);

  const topManualButton = topManual ? (
    <ManualEmbed pdfPath={topManual.path} title={topManual.title} buttonLabel="Manual" />
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
          tabs={peptideTabs}
          activeTab={activePeptideTab}
          onChange={setActivePeptideTab}
          rightContent={topManualButton}
        />
      );
    }

    if (activeSection === "singleProtein") {
      return (
        <TopTabs
          tabs={singleProteinTabs}
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
          tabs={externalTabs}
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
    visibleSummaryTabs,
    visiblePhosphoTabs,
  ]);

  function renderContent() {
    if (activeSection === "completeness") {
      if (activeCompletenessTab === "missingPlot") {
        return <MissingValuePlotPage />;
      }

      if (activeCompletenessTab === "heatmap") {
        return <MissingValueHeatmapPage />;
      }

      return <CompletenessTablesPage />;
    }

    if (activeSection === "qc") {
      if (activeQcTab === "coverage") {
        return <CoveragePlotPage />;
      }

      if (activeQcTab === "histogram") {
        return <HistogramIntensityPage />;
      }

      if (activeQcTab === "boxplot") {
        return <BoxplotIntensityPage />;
      }

      if (activeQcTab === "cv") {
        return <CovPlotPage />;
      }

      if (activeQcTab === "pca") {
        return <PrincipalComponentAnalysisPage />;
      }

      if (activeQcTab === "abundance") {
        return <AbundancePlotPage />;
      }

      return <CorrelationPlotPage />;
    }

    if (activeSection === "stats") {
      if (activeStatsTab === "volcano") {
        return <VolcanoPlotPage />;
      }

      if (activeStatsTab === "volcanoControl") {
        return <VolcanoPlotControlPage />;
      }

      if (activeStatsTab === "gsea") {
        return <GseaPage />;
      }

      if (activeStatsTab === "pathwayHeatmap") {
        return <PathwayHeatmapPage />;
      }

      if (IS_VIEWER_MODE) {
        return <VolcanoPlotPage />;
      }

      return <SimulationPage />;
    }

    if (activeSection === "peptide") {
      if (activePeptideTab === "rtPlot") {
        return <RtPlotPage />;
      }

      if (activePeptideTab === "modification") {
        return <ModificationPlotPage />;
      }

      if (activePeptideTab === "missedCleavage") {
        return <MissedCleavagePlotPage />;
      }

      return <SequenceCoveragePage />;
    }

    if (activeSection === "singleProtein") {
      if (activeSingleProteinTab === "boxplot") {
        return <ProteinBoxplotPage />;
      }

      if (activeSingleProteinTab === "lineplot") {
        return <ProteinLineplotPage />;
      }

      return <PhosphositesOnProteinHeatmapPage />;
    }

    if (activeSection === "phospho") {
      if (activePhosphoTab === "phosphositePlot") {
        return <PhosphositePlotPage />;
      }

      if (activePhosphoTab === "coverage") {
        return <PhosphositeCoveragePage />;
      }

      if (activePhosphoTab === "ksea") {
        if (IS_VIEWER_MODE) {
          return <PhosphositePlotPage />;
        }
        return <KseaPage />;
      }

      if (activePhosphoTab === "distribution") {
        return <PhosphositeDistributionPage />;
      }

      if (activePhosphoTab === "phosprotRegulation") {
        return <PhosprotRegulationPage />;
      }

      return <StyPlotPage />;
    }

    if (activeSection === "comparison") {
      if (activeComparisonTab === "pearson") {
        return <PearsonCorrelationPage />;
      }
      return <VennDiagramPage />;
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
        return <PeptideCollapsePage />;
      }
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
        return <DistributionPage />;
      }

      if (activeDataTab === "verification") {
        return <VerificationPage />;
      }

      if (activeDataTab === "translator") {
        return <IdTranslatorPage />;
      }

      if (activeDataTab === "conditionPalette") {
        return <ColorsPage />;
      }
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

  return (
    <AppShell
      activeSection={activeSection}
      onSectionChange={setActiveSection}
      sections={visibleSections}
      topBar={topBar}
    >
      {renderContent()}
    </AppShell>
  );
}

function sectionTitle(section: SidebarSection): string {
  switch (section) {
    case "data":
      return "Data";
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
  }
}
