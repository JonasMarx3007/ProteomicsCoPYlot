import StatisticalAnalysisPage from "./StatisticalAnalysisPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function AnovaPage({ onContextModeChange }: Props) {
  return <StatisticalAnalysisPage activeTab="anova" onContextModeChange={onContextModeChange} />;
}
