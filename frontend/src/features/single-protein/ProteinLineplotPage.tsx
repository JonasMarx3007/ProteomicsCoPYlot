import SingleProteinPage from "./SingleProteinPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function ProteinLineplotPage({ onContextModeChange }: Props) {
  return <SingleProteinPage activeTab="lineplot" onContextModeChange={onContextModeChange} />;
}
