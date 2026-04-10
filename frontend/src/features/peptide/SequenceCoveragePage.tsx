import PeptideLevelPage from "./PeptideLevelPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function SequenceCoveragePage({ onContextModeChange }: Props) {
  return <PeptideLevelPage activeTab="sequenceCoverage" onContextModeChange={onContextModeChange} />;
}
