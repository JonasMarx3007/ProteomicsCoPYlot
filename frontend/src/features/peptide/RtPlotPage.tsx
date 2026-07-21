import type { ReactNode } from "react";
import PeptideLevelPage from "./PeptideLevelPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function RtPlotPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <PeptideLevelPage activeTab="rtPlot" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
