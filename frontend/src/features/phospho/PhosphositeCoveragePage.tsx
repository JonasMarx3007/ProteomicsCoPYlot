import PhosphoSpecificPage from "./PhosphoSpecificPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function PhosphositeCoveragePage({ onContextModeChange }: Props) {
  return <PhosphoSpecificPage activeTab="coverage" onContextModeChange={onContextModeChange} />;
}
