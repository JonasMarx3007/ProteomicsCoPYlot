import type { ReactNode } from "react";
import PhosphoSpecificPage from "./PhosphoSpecificPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function PhosphositeCoveragePage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <PhosphoSpecificPage activeTab="coverage" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
