import type { ReactNode } from "react";
import StatisticalAnalysisPage from "./StatisticalAnalysisPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function VolcanoPlotPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <StatisticalAnalysisPage activeTab="volcano" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
