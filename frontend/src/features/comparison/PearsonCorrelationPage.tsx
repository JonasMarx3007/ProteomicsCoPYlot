import type { ReactNode } from "react";
import ComparisonPipelinePage from "./ComparisonPipelinePage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function PearsonCorrelationPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <ComparisonPipelinePage activeTab="pearson" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
