import SingleProteinPage from "./SingleProteinPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function PhosphositesOnProteinHeatmapPage({ onContextModeChange }: Props) {
  return <SingleProteinPage activeTab="heatmap" onContextModeChange={onContextModeChange} />;
}
