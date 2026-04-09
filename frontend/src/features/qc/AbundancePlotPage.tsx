import QCPipelinePage from "./QCPipelinePage";

type Props = {
  onWorkflowScopeChange?: (workflow: string) => void;
};

export default function AbundancePlotPage({ onWorkflowScopeChange }: Props) {
  return <QCPipelinePage activeTab="abundance" onWorkflowScopeChange={onWorkflowScopeChange} />;
}
