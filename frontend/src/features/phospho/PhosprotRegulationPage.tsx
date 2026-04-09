import PhosphoSpecificPage from "./PhosphoSpecificPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function PhosprotRegulationPage({ onContextModeChange }: Props) {
  return <PhosphoSpecificPage activeTab="phosprotRegulation" onContextModeChange={onContextModeChange} />;
}
