import CompletenessPage from "./CompletenessPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function MissingValueHeatmapPage({ onContextModeChange }: Props) {
  return <CompletenessPage activeTab="heatmap" onContextModeChange={onContextModeChange} />;
}
