import type { ReactNode } from "react";
import PeptideLevelPage from "./PeptideLevelPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function SequenceCoveragePage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <PeptideLevelPage activeTab="sequenceCoverage" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
