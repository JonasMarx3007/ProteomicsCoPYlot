import SingleProteinPage from "./SingleProteinPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function ProteinBoxplotPage({ onContextModeChange }: Props) {
  return <SingleProteinPage activeTab="boxplot" onContextModeChange={onContextModeChange} />;
}
