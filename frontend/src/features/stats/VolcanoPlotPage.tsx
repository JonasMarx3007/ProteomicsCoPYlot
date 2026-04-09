import StatisticalAnalysisPage from "./StatisticalAnalysisPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function VolcanoPlotPage({ onContextModeChange }: Props) {
  return <StatisticalAnalysisPage activeTab="volcano" onContextModeChange={onContextModeChange} />;
}
