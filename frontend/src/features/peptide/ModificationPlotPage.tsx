import type { ReactNode } from "react";
import PeptideLevelPage from "./PeptideLevelPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function ModificationPlotPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <PeptideLevelPage activeTab="modification" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
