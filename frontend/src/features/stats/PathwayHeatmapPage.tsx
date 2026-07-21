import type { ReactNode } from "react";
import StatisticalAnalysisPage from "./StatisticalAnalysisPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function PathwayHeatmapPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <StatisticalAnalysisPage activeTab="pathwayHeatmap" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
