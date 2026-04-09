import ComparisonPipelinePage from "./ComparisonPipelinePage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function VennDiagramPage({ onContextModeChange }: Props) {
  return <ComparisonPipelinePage activeTab="venn" onContextModeChange={onContextModeChange} />;
}
