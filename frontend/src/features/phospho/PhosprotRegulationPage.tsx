import type { ReactNode } from "react";
import PhosphoSpecificPage from "./PhosphoSpecificPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function PhosprotRegulationPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <PhosphoSpecificPage activeTab="phosprotRegulation" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
