import StatisticalAnalysisPage from "./StatisticalAnalysisPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function PathwayHeatmapPage({ onContextModeChange }: Props) {
  return <StatisticalAnalysisPage activeTab="pathwayHeatmap" onContextModeChange={onContextModeChange} />;
}
