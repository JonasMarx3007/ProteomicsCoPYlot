import QCPipelinePage from "./QCPipelinePage";

type Props = {
  onWorkflowScopeChange?: (workflow: string) => void;
};

export default function HistogramIntensityPage({ onWorkflowScopeChange }: Props) {
  return <QCPipelinePage activeTab="histogram" onWorkflowScopeChange={onWorkflowScopeChange} />;
}
