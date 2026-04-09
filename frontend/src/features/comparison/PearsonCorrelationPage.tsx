import ComparisonPipelinePage from "./ComparisonPipelinePage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function PearsonCorrelationPage({ onContextModeChange }: Props) {
  return <ComparisonPipelinePage activeTab="pearson" onContextModeChange={onContextModeChange} />;
}
