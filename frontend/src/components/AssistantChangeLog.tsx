import { useState, useSyncExternalStore } from "react";
import {
  assistantChanges, subscribeAssistantChanges, undoLastAssistantRequest, undoableAssistantChanges,
} from "../lib/assistantControls";

function shown(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(", ") : "none";
  if (typeof value === "boolean") return value ? "on" : "off";
  return String(value ?? "") || "empty";
}

/**
 * The controls the assistant changed in the most recent request, newest last,
 * with one undo that takes all of them back. Each sent message starts a new
 * scope: earlier requests are counted, not undoable (2026-10-13). Shown in the
 * assistant sidebar only: what was finally used is what the report describes,
 * however it was set.
 */
export default function AssistantChangeLog() {
  const all = useSyncExternalStore(subscribeAssistantChanges, assistantChanges, assistantChanges);
  const changes = useSyncExternalStore(subscribeAssistantChanges, undoableAssistantChanges, undoableAssistantChanges);
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  const earlier = all.length - changes.length;
  if (!all.length && !message) return null;
  return (
    <details className="mb-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700">
      <summary className="cursor-pointer font-medium">
        Changes made by the assistant ({changes.length})
      </summary>
      {changes.length ? (
        <ol className="mt-2 max-h-40 space-y-1 overflow-y-auto" aria-label="Assistant changes">
          {changes.map((change) => (
            <li key={change.id}>
              <span className="font-medium">{change.label}</span>: {shown(change.before)} → {shown(change.after)}
              {change.module ? <span className="text-slate-500"> ({change.module})</span> : null}
            </li>
          ))}
        </ol>
      ) : null}
      {earlier > 0 ? (
        <div className="mt-2 text-slate-500">{earlier} earlier {earlier === 1 ? "change" : "changes"} from previous requests (not undoable).</div>
      ) : null}
      {message ? (
        <div className={`mt-2 ${message.error ? "text-red-700" : "text-slate-600"}`} role="status">{message.text}</div>
      ) : null}
      {changes.length ? (
        <button
          type="button"
          className="mt-2 rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 transition hover:bg-slate-100"
          onClick={() => {
            try {
              setMessage({ text: undoLastAssistantRequest(), error: false });
            } catch (error) {
              setMessage({ text: error instanceof Error ? error.message : "The change could not be undone.", error: true });
            }
          }}
        >
          {changes.length === 1 ? "Undo last change" : `Undo last request (${changes.length} changes)`}
        </button>
      ) : null}
    </details>
  );
}
