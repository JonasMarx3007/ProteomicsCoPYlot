import PhosphoSpecificPage from "./PhosphoSpecificPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function PhosphositeDistributionPage({ onContextModeChange }: Props) {
  return <PhosphoSpecificPage activeTab="distribution" onContextModeChange={onContextModeChange} />;
}
