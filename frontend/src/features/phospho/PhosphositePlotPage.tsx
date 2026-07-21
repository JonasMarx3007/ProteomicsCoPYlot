import type { ReactNode } from "react";
import PhosphoSpecificPage from "./PhosphoSpecificPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function PhosphositePlotPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <PhosphoSpecificPage activeTab="phosphositePlot" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
