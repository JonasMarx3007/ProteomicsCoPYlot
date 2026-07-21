import type { ReactNode } from "react";
import ComparisonPipelinePage from "./ComparisonPipelinePage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function VennDiagramPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <ComparisonPipelinePage activeTab="venn" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
