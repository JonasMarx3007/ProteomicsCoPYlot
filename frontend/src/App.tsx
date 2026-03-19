import { useMemo, useState } from "react";
import AppShell from "./components/AppShell";
import TopTabs from "./components/TopTabs";
import UploadPage from "./features/upload/UploadPage";
import MetaPage from "./features/metadata/MetaPage";
import type {
  DataTab,
  DatasetPreviewResponse,
  SidebarSection,
} from "./lib/types";

const dataTabs: { key: DataTab; label: string }[] = [
  { key: "upload", label: "Upload" },
  { key: "meta", label: "Meta" },
];

export default function App() {
  const [activeSection, setActiveSection] = useState<SidebarSection>("data");
  const [activeDataTab, setActiveDataTab] = useState<DataTab>("upload");
  const [currentDataset, setCurrentDataset] =
    useState<DatasetPreviewResponse | null>(null);

  const topBar = useMemo(() => {
    if (activeSection !== "data") return null;

    return (
      <TopTabs
        tabs={dataTabs}
        activeTab={activeDataTab}
        onChange={setActiveDataTab}
      />
    );
  }, [activeSection, activeDataTab]);

  function renderContent() {
    if (activeSection === "data") {
      if (activeDataTab === "upload") {
        return <UploadPage onDatasetUploaded={setCurrentDataset} />;
      }

      if (activeDataTab === "meta") {
        return <MetaPage dataset={currentDataset} />;
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