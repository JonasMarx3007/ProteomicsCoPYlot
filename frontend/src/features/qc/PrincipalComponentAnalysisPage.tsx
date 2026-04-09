import QCPipelinePage from "./QCPipelinePage";

type Props = {
  onWorkflowScopeChange?: (workflow: string) => void;
  onPcaContextModeChange?: (mode: string) => void;
};

export default function PrincipalComponentAnalysisPage({ onWorkflowScopeChange, onPcaContextModeChange }: Props) {
  return (
    <QCPipelinePage
      activeTab="pca"
      onWorkflowScopeChange={onWorkflowScopeChange}
      onPcaContextModeChange={onPcaContextModeChange}
    />
  );
}
