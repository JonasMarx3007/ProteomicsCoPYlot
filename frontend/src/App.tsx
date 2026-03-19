import { useEffect, useMemo, useState } from "react";
import AppShell from "./components/AppShell";
import TopTabs from "./components/TopTabs";
import UploadPage from "./features/upload/UploadPage";
import AnnotationPage from "./features/metadata/AnnotationPage";
import CompletenessPage from "./features/data/CompletenessPage";
import ImputationPage from "./features/data/ImputationPage";
import DistributionPage from "./features/data/DistributionPage";
import VerificationPage from "./features/data/VerificationPage";
import QCPipelinePage from "./features/qc/QCPipelinePage";
import type { CompletenessTab, DataTab, QcTab, SidebarSection } from "./lib/types";

const dataTabs: { key: DataTab; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "annotation", label: "Annotation" },
  { key: "imputation", label: "Imputation" },
  { key: "distribution", label: "Distribution" },
  { key: "verification", label: "Verification" },
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

export default function App() {
  const [activeSection, setActiveSection] = useState<SidebarSection>("data");
  const [activeDataTab, setActiveDataTab] = useState<DataTab>("upload");
  const [activeQcTab, setActiveQcTab] = useState<QcTab>("coverage");
  const [activeCompletenessTab, setActiveCompletenessTab] = useState<CompletenessTab>("missingPlot");

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

    return null;
  }, [activeSection, activeDataTab, activeQcTab, activeCompletenessTab]);

  function renderContent() {
    if (activeSection === "completeness") {
      return <CompletenessPage activeTab={activeCompletenessTab} />;
    }

    if (activeSection === "qc") {
      return <QCPipelinePage activeTab={activeQcTab} />;
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
