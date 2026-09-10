import { useId } from "react";

type Props = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: (string | { value: string; label: string })[];
  placeholder?: string;
};

export default function SelectField({ label, value, onChange, options, placeholder }: Props) {
  const fieldId = useId();
  return (
    <div>
      <label htmlFor={fieldId} className="mb-2 block text-sm font-medium text-slate-700">{label}</label>
      <select id={fieldId}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900"
      >
        {placeholder ? <option value="">{placeholder}</option> : null}
        {options.map((option) => {
          const item = typeof option === "string" ? { value: option, label: option } : option;
          return <option key={item.value} value={item.value}>{item.label}</option>;
        })}
      </select>
    </div>
  );
}
