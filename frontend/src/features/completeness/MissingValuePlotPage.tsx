import CompletenessPage from "./CompletenessPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function MissingValuePlotPage({ onContextModeChange }: Props) {
  return <CompletenessPage activeTab="missingPlot" onContextModeChange={onContextModeChange} />;
}
