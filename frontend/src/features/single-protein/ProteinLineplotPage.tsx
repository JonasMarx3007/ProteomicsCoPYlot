import type { ReactNode } from "react";
import SingleProteinPage from "./SingleProteinPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
  advancedPlotOptions?: ReactNode;
};

export default function ProteinLineplotPage({ onContextModeChange, advancedPlotOptions }: Props) {
  return <SingleProteinPage activeTab="lineplot" onContextModeChange={onContextModeChange} advancedPlotOptions={advancedPlotOptions} />;
}
