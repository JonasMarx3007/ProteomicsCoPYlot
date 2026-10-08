import { useId, useState, type ElementType } from "react";
import { AssistantInput } from "./AssistantFields";

function formatValue(value: number) {
  return Number.isFinite(value) ? String(value) : "";
}

function parseDraft(value: string): number | null {
  const normalized = value.trim().replace(",", ".");
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

type Props = {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
  /** Returns a message to refuse the entered value, or null to accept it. */
  validate?: (value: number) => string | null;
  onValidationError?: (message: string | null) => void;
  /** false renders a plain input, outside the assistant's control list. */
  assistant?: boolean;
  /** A presentation setting (size, DPI) the assistant may change without asking. */
  appearance?: boolean;
  min?: number;
  max?: number;
  /** Greyed out where the active renderer does not read this setting. */
  disabled?: boolean;
  disabledHint?: string;
};

/**
 * A number you type, committed when you leave the field or press Enter.
 *
 * Every number input in the tool is this one. Copies used to commit on every keystroke:
 * typing "0.05" set the threshold to 0, then 0, then 0.05, each one a new
 * request and a redrawn figure, and deleting a digit rewrote the value behind
 * the cursor. The draft here is the text being typed; the number only changes
 * on blur or Enter, and an unparseable or refused draft snaps back to the value
 * that is actually in force. A comma is read as a decimal point.
 */
export default function NumberField({
  label, value, onChange, step = 1, validate, onValidationError, assistant = true,
  appearance = false, min, max, disabled = false, disabledHint,
}: Props) {
  const fieldId = useId();
  const [draft, setDraft] = useState<{ value: number; text: string } | null>(null);

  if (draft !== null && !Object.is(draft.value, value)) {
    setDraft(null);
  }

  const commit = () => {
    const nextValue = parseDraft(draft?.text ?? formatValue(value));
    if (nextValue == null) {
      setDraft(null);
      return;
    }
    const validationError = validate?.(nextValue) ?? null;
    if (validationError) {
      onValidationError?.(validationError);
      setDraft(null);
      return;
    }
    onValidationError?.(null);
    onChange(nextValue);
    // The parent may round, clamp or refuse the value, including to its
    // unchanged current value. Once committed, display that accepted value.
    setDraft(null);
  };

  const Input: ElementType = assistant ? AssistantInput : "input";
  return (
    <div data-assistant-appearance={appearance ? "true" : undefined}>
      <label htmlFor={fieldId}
        className={`mb-2 block text-sm font-medium ${disabled ? "text-slate-400" : "text-slate-700"}`}>{label}</label>
      <Input id={fieldId} aria-label={label}
        type="text"
        lang="en-US"
        inputMode="decimal"
        data-assistant-permission={appearance ? "view" : undefined}
        min={min}
        max={max}
        disabled={disabled}
        title={disabled ? disabledHint : undefined}
        value={draft?.text ?? formatValue(value)}
        step={step}
        onChange={(event: { target: { value: string } }) => setDraft({ value, text: event.target.value.replace(",", ".") })}
        onBlur={commit}
        onKeyDown={(event: { key: string; preventDefault: () => void }) => {
          if (event.key === "Enter") {
            event.preventDefault();
            commit();
          }
        }}
        className="w-full rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-slate-900 disabled:cursor-not-allowed disabled:border-slate-200 disabled:bg-slate-100 disabled:text-slate-400"
      />
      {disabled && disabledHint ? <p className="mt-1 text-xs text-slate-400">{disabledHint}</p> : null}
    </div>
  );
}
