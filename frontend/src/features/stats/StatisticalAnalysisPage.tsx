import type { ReactNode } from "react";
import { useCurrentDatasetsSnapshot } from "../../lib/datasetAvailability";
import type { ContextMode, StatsTab } from "../../lib/types";
import SectionCard from "../../components/SectionCard";
import { InfoSection } from "./statsShared";
import { VolcanoPanel } from "./VolcanoPanel";
import { AnovaPanel } from "./AnovaPanel";
import { OraPanel } from "./OraPanel";
import { PathwayHeatmapPanel } from "./PathwayHeatmapPanel";
import { SimulationPanel } from "./SimulationPanel";

type Props = {
  activeTab: StatsTab;
  onContextModeChange?: (mode: ContextMode | null) => void;
  advancedPlotOptions?: ReactNode;
};

export default function StatisticalAnalysisPage({ activeTab, onContextModeChange, advancedPlotOptions }: Props) {
  const { kindOptions } = useCurrentDatasetsSnapshot();

  if (kindOptions.length === 0) {
    return (
      <div className="space-y-6">
        <SectionCard title="Statistical Analysis">
          <InfoSection message="Upload a protein, phospho, or phosphoprotein dataset in the Data tab to enable statistical plots." />
        </SectionCard>
      </div>
    );
  }

  if (activeTab === "volcano") return <VolcanoPanel kindOptions={kindOptions} onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
  if (activeTab === "anova") return <AnovaPanel kindOptions={kindOptions} onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
  if (activeTab === "ora") return <OraPanel kindOptions={kindOptions} onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
  if (activeTab === "pathwayHeatmap") return <PathwayHeatmapPanel kindOptions={kindOptions} onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
  return <SimulationPanel kindOptions={kindOptions} onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
