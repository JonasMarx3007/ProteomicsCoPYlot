import { useId } from "react";
import { AssistantInput } from "./AssistantFields";

export default function TextField({
  label, value, onChange, placeholder,
}: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  const fieldId = useId();
  return (
    <div>
      <label htmlFor={fieldId} className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <AssistantInput id={fieldId} aria-label={label}
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
      />
    </div>
  );
}
