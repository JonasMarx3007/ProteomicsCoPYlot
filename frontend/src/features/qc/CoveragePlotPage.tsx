import QCPipelinePage from "./QCPipelinePage";

type Props = {
  onWorkflowScopeChange?: (workflow: string) => void;
};

export default function CoveragePlotPage({ onWorkflowScopeChange }: Props) {
  return <QCPipelinePage activeTab="coverage" onWorkflowScopeChange={onWorkflowScopeChange} />;
}
