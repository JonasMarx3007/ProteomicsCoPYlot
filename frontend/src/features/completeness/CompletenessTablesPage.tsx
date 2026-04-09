import CompletenessPage from "./CompletenessPage";

type Props = {
  onContextModeChange?: (mode: string) => void;
};

export default function CompletenessTablesPage({ onContextModeChange }: Props) {
  return <CompletenessPage activeTab="tables" onContextModeChange={onContextModeChange} />;
}
