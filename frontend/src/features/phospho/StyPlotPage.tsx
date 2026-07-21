import type { ReactNode } from "react";
import PhosphoSpecificPage from "./PhosphoSpecificPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function StyPlotPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <PhosphoSpecificPage activeTab="sty" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
