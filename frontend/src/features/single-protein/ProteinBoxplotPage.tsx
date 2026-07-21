import type { ReactNode } from "react";
import SingleProteinPage from "./SingleProteinPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function ProteinBoxplotPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <SingleProteinPage activeTab="boxplot" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
