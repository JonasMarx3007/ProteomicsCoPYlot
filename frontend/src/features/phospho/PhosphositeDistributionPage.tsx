import type { ReactNode } from "react";
import PhosphoSpecificPage from "./PhosphoSpecificPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function PhosphositeDistributionPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <PhosphoSpecificPage activeTab="distribution" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
