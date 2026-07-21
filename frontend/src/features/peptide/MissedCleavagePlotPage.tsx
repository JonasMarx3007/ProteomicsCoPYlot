import type { ReactNode } from "react";
import PeptideLevelPage from "./PeptideLevelPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function MissedCleavagePlotPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <PeptideLevelPage activeTab="missedCleavage" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
