import PeptideLevelPage from "./PeptideLevelPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function MissedCleavagePlotPage({ onContextModeChange }: Props) {
  return <PeptideLevelPage activeTab="missedCleavage" onContextModeChange={onContextModeChange} />;
}
