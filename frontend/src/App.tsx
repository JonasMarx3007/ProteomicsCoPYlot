import { useEffect, useMemo, useState } from "react";
import AppShell from "./components/AppShell";
import TopTabs from "./components/TopTabs";
import UploadPage from "./features/upload/UploadPage";
import AnnotationPage from "./features/metadata/AnnotationPage";
import ImputationPage from "./features/data/ImputationPage";
import DistributionPage from "./features/data/DistributionPage";
import VerificationPage from "./features/data/VerificationPage";
import IdTranslatorPage from "./features/data/IdTranslatorPage";
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
import PearsonCorrelationPage from "./features/comparison/PearsonCorrelationPage";
import VennDiagramPage from "./features/comparison/VennDiagramPage";
import PeptideCollapsePage from "./features/external/PeptideCollapsePage";
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
  StatsTab,
} from "./lib/types";

const dataTabs: { key: DataTab; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "annotation", label: "Annotation" },
  { key: "imputation", label: "Imputation" },
  { key: "distribution", label: "Distribution" },
  { key: "verification", label: "Verification" },
  { key: "translator", label: "ID Translator" },
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
  { key: "distribution", label: "Phosphosite Distribution" },
  { key: "sty", label: "STY Plot" },
];

const comparisonTabs: { key: ComparisonTab; label: string }[] = [
  { key: "pearson", label: "Pearson Correlation" },
  { key: "venn", label: "Venn Diagram" },
];

const externalTabs: { key: ExternalTab; label: string }[] = [
  { key: "peptideCollapse", label: "Peptide Collapse Function" },
];

export default function App() {
  const [activeSection, setActiveSection] = useState<SidebarSection>("data");
  const [activeDataTab, setActiveDataTab] = useState<DataTab>("upload");
  const [activeQcTab, setActiveQcTab] = useState<QcTab>("coverage");
  const [activeCompletenessTab, setActiveCompletenessTab] = useState<CompletenessTab>("missingPlot");
  const [activeStatsTab, setActiveStatsTab] = useState<StatsTab>("volcano");
  const [activePeptideTab, setActivePeptideTab] = useState<PeptideTab>("rtPlot");
  const [activeSingleProteinTab, setActiveSingleProteinTab] = useState<SingleProteinTab>("boxplot");
  const [activePhosphoTab, setActivePhosphoTab] = useState<PhosphoTab>("phosphositePlot");
  const [activeComparisonTab, setActiveComparisonTab] = useState<ComparisonTab>("pearson");
  const [activeExternalTab, setActiveExternalTab] = useState<ExternalTab>("peptideCollapse");

  useEffect(() => {
    document.title = "Proteomics CoPYlot";
  }, []);

  const topBar = useMemo(() => {
    if (activeSection === "data") {
      return (
        <TopTabs
          tabs={dataTabs}
          activeTab={activeDataTab}
          onChange={setActiveDataTab}
        />
      );
    }

    if (activeSection === "qc") {
      return (
        <TopTabs
          tabs={qcTabs}
          activeTab={activeQcTab}
          onChange={setActiveQcTab}
        />
      );
    }

    if (activeSection === "completeness") {
      return (
        <TopTabs
          tabs={completenessTabs}
          activeTab={activeCompletenessTab}
          onChange={setActiveCompletenessTab}
        />
      );
    }

    if (activeSection === "stats") {
      return (
        <TopTabs
          tabs={statsTabs}
          activeTab={activeStatsTab}
          onChange={setActiveStatsTab}
        />
      );
    }

    if (activeSection === "peptide") {
      return (
        <TopTabs
          tabs={peptideTabs}
          activeTab={activePeptideTab}
          onChange={setActivePeptideTab}
        />
      );
    }

    if (activeSection === "singleProtein") {
      return (
        <TopTabs
          tabs={singleProteinTabs}
          activeTab={activeSingleProteinTab}
          onChange={setActiveSingleProteinTab}
        />
      );
    }

    if (activeSection === "phospho") {
      return (
        <TopTabs
          tabs={phosphoTabs}
          activeTab={activePhosphoTab}
          onChange={setActivePhosphoTab}
        />
      );
    }

    if (activeSection === "comparison") {
      return (
        <TopTabs
          tabs={comparisonTabs}
          activeTab={activeComparisonTab}
          onChange={setActiveComparisonTab}
        />
      );
    }

    if (activeSection === "external") {
      return (
        <TopTabs
          tabs={externalTabs}
          activeTab={activeExternalTab}
          onChange={setActiveExternalTab}
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
    activeExternalTab,
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

      if (activePhosphoTab === "distribution") {
        return <PhosphositeDistributionPage />;
      }

      return <StyPlotPage />;
    }

    if (activeSection === "comparison") {
      if (activeComparisonTab === "pearson") {
        return <PearsonCorrelationPage />;
      }
      return <VennDiagramPage />;
    }

    if (activeSection === "external") {
      if (activeExternalTab === "peptideCollapse") {
        return <PeptideCollapsePage />;
      }
    }

    if (activeSection === "data") {
      if (activeDataTab === "upload") {
        return <UploadPage />;
      }

      if (activeDataTab === "annotation") {
        return <AnnotationPage />;
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
