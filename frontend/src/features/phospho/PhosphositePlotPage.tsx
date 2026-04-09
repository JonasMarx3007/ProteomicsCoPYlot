import PhosphoSpecificPage from "./PhosphoSpecificPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function PhosphositePlotPage({ onContextModeChange }: Props) {
  return <PhosphoSpecificPage activeTab="phosphositePlot" onContextModeChange={onContextModeChange} />;
}
