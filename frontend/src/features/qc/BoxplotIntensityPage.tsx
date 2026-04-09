import QCPipelinePage from "./QCPipelinePage";

type Props = {
  onModeChange?: (mode: string) => void;
  onWorkflowScopeChange?: (workflow: string) => void;
};

export default function BoxplotIntensityPage({ onModeChange, onWorkflowScopeChange }: Props) {
  return (
    <QCPipelinePage
      activeTab="boxplot"
      onBoxplotModeChange={onModeChange}
      onWorkflowScopeChange={onWorkflowScopeChange}
    />
  );
}
