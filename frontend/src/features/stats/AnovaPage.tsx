import type { ReactNode } from "react";
import StatisticalAnalysisPage from "./StatisticalAnalysisPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function AnovaPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <StatisticalAnalysisPage activeTab="anova" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
