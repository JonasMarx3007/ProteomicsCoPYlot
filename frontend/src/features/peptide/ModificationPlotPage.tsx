import PeptideLevelPage from "./PeptideLevelPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function ModificationPlotPage({ onContextModeChange }: Props) {
  return <PeptideLevelPage activeTab="modification" onContextModeChange={onContextModeChange} />;
}
