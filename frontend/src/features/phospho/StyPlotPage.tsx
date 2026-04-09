import PhosphoSpecificPage from "./PhosphoSpecificPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function StyPlotPage({ onContextModeChange }: Props) {
  return <PhosphoSpecificPage activeTab="sty" onContextModeChange={onContextModeChange} />;
}
