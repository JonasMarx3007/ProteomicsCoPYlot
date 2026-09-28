import { useId } from "react";
import { AssistantSelect } from "./AssistantFields";

type Option = string | { value: string; label: string };

type Props = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: Option[];
  /** Display names for plain string options, by option value. */
  labels?: Record<string, string>;
  /** Leading empty option, shown whether or not there are other options. */
  placeholder?: string;
  /** Sole option when the list is empty, so the control never looks broken. */
  emptyLabel?: string;
  /** Greyed out where the active renderer does not read this setting. */
  disabled?: boolean;
  disabledHint?: string;
};

/**
 * The one dropdown.
 *
 * Nine pages carried their own copy of this, in two DOM shapes, and the name a
 * screen reader or the assistant reports depends on that shape: it comes from
 * aria-label, from the label element that points at the control, or from
 * neither. The shape kept here is the one the shared component already used --
 * a wrapper div, a label bound by htmlFor, and aria-label -- so every dropdown
 * in the app is named the same way for a reader, for the assistant and for the
 * browser tests.
 */
export default function SelectField({
  label, value, onChange, options, labels, placeholder, emptyLabel, disabled = false, disabledHint,
}: Props) {
  const fieldId = useId();
  const items = options.map((option) =>
    typeof option === "string" ? { value: option, label: labels?.[option] ?? option } : option
  );
  return (
    <div>
      <label
        htmlFor={fieldId}
        className={`mb-2 block text-sm font-medium ${disabled ? "text-slate-400" : "text-slate-700"}`}
      >
        {label}
      </label>
      <AssistantSelect id={fieldId} aria-label={label}
        value={value}
        disabled={disabled}
        title={disabled ? disabledHint : undefined}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400"
      >
        {placeholder ? <option value="">{placeholder}</option> : null}
        {items.length === 0 && emptyLabel ? <option value="">{emptyLabel}</option> : null}
        {items.map((item) => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </AssistantSelect>
      {disabled && disabledHint ? <p className="mt-1 text-xs text-slate-400">{disabledHint}</p> : null}
    </div>
  );
}
