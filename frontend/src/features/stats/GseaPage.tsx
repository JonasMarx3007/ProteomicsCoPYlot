import type { ReactNode } from "react";
import StatisticalAnalysisPage from "./StatisticalAnalysisPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function GseaPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <StatisticalAnalysisPage activeTab="gsea" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
