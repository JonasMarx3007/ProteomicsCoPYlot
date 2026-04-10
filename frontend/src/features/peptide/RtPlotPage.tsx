import PeptideLevelPage from "./PeptideLevelPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function RtPlotPage({ onContextModeChange }: Props) {
  return <PeptideLevelPage activeTab="rtPlot" onContextModeChange={onContextModeChange} />;
}
