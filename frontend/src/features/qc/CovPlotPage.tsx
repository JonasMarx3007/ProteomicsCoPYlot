import QCPipelinePage from "./QCPipelinePage";

type Props = {
  onWorkflowScopeChange?: (workflow: string) => void;
};

export default function CovPlotPage({ onWorkflowScopeChange }: Props) {
  return <QCPipelinePage activeTab="cv" onWorkflowScopeChange={onWorkflowScopeChange} />;
}
