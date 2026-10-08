import { AssistantInput } from "./AssistantFields";

const LABEL = "inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700";

/** The one checkbox. `assistant={false}` keeps it out of the assistant's control list. */
export default function CheckboxField({
  label, checked, onChange, assistant = true,
}: { label: string; checked: boolean; onChange: (checked: boolean) => void; assistant?: boolean }) {
  if (!assistant) {
    return (
      <label className={LABEL}>
        <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
        {label}
      </label>
    );
  }
  return (
    <label className={LABEL}>
      <AssistantInput type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  );
}
