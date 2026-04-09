import QCPipelinePage from "./QCPipelinePage";

type Props = {
  onWorkflowScopeChange?: (workflow: string) => void;
};

export default function CorrelationPlotPage({ onWorkflowScopeChange }: Props) {
  return <QCPipelinePage activeTab="correlation" onWorkflowScopeChange={onWorkflowScopeChange} />;
}
