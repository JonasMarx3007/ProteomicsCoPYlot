import type { ReactNode } from "react";
import SingleProteinPage from "./SingleProteinPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function PhosphositesOnProteinHeatmapPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <SingleProteinPage activeTab="heatmap" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
