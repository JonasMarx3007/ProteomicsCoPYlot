import StatisticalAnalysisPage from "./StatisticalAnalysisPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function GseaPage({ onContextModeChange }: Props) {
  return <StatisticalAnalysisPage activeTab="gsea" onContextModeChange={onContextModeChange} />;
}
