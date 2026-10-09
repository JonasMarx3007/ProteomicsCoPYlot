import { createContext, useContext, useId, useLayoutEffect, useRef, type ChangeEvent, type FocusEvent } from "react";
import { flushSync } from "react-dom";

export type ControlValue = string | boolean | string[];
export type AssistantControl = {
  appearance?: boolean;
  optionLabels?: Record<string, string>;
  permission: "view" | "confirm";
  id: string; label: string; type: "text" | "number" | "color" | "checkbox" | "select" | "multiple" | "button";
  value: ControlValue; options: string[]; optionCount: number; min?: number; max?: number;
  optionQuery?: string; optionMatchCount?: number;
};
export type AssistantAction = { type: "navigate" | "set_control" | "search_options" | "activate_control" | "focus_canvas" | "add_canvas_tiles" | "save_style" | "apply_style"; target: string; value: ControlValue };
type Element = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
type Binding = { read: () => AssistantControl | null; apply: (value: ControlValue) => void; commit: () => void };
const controls = new Map<string, Binding>();
const buttons = new Map<string, { read: () => AssistantControl | null; activate: () => string }>();
export const AssistantControlScope = createContext(false);

/** One control the assistant changed: what it was, and what it became. */
export type AssistantChange = {
  id: number; at: string; module: string; target: string; label: string; before: ControlValue; after: ControlValue;
};
// Kept for the session so a person can see what the assistant changed and take
// the last change back. Replaced, never mutated, so React can subscribe to it.
let changeLog: readonly AssistantChange[] = [];
let nextChangeId = 1;
const changeListeners = new Set<() => void>();
const CHANGE_LOG_LIMIT = 50;
function publishChanges(next: readonly AssistantChange[]) {
  changeLog = next;
  changeListeners.forEach(listener => listener());
}
export function subscribeAssistantChanges(listener: () => void): () => void {
  changeListeners.add(listener);
  return () => { changeListeners.delete(listener); };
}
export function assistantChanges(): readonly AssistantChange[] { return changeLog; }
function recordAssistantChange(change: Omit<AssistantChange, "id" | "at" | "module">) {
  const entry = { ...change, id: nextChangeId++, at: new Date().toISOString(), module: surfaceModule };
  publishChanges([...changeLog, entry].slice(-CHANGE_LOG_LIMIT));
}

/**
 * Put the control the assistant changed last back to its earlier value.
 *
 * Refused rather than guessed when it cannot be done safely: the control is not
 * on screen (another page is open), or its value is no longer the one the
 * assistant set (someone changed it since). The entry stays in the log then.
 */
export function undoLastAssistantChange(): string {
  const last = changeLog[changeLog.length - 1];
  if (!last) throw new Error("There is no assistant change to undo.");
  const binding = controls.get(last.target);
  const control = binding?.read();
  if (!binding || !control) {
    throw new Error(`${last.label} is not on screen. Open the page where the assistant changed it, then undo.`);
  }
  if (JSON.stringify(control.value) !== JSON.stringify(last.after)) {
    throw new Error(`${last.label} has been changed since the assistant set it, so it was not undone.`);
  }
  flushSync(() => binding.apply(last.before));
  flushSync(() => controls.get(last.target)?.commit());
  const actual = controls.get(last.target)?.read();
  if (!actual || JSON.stringify(actual.value) !== JSON.stringify(last.before)) {
    throw new Error(`${last.label} did not accept its earlier value. Check the plot controls.`);
  }
  publishChanges(changeLog.slice(0, -1));
  return `Set ${last.label} back to ${JSON.stringify(last.before)}.`;
}
let surfaceModule = "";
export function assistantSurfaceReady(module: string) { return surfaceModule === module; }
export function useAssistantSurface(module: string) {
  useLayoutEffect(() => {
    surfaceModule = module;
    return () => { if (surfaceModule === module) surfaceModule = ""; };
  }, [module]);
}

// The full chain of enclosing groups, outermost first: the X and Y axis cards
// both contain an "Axis label" group, and the innermost name alone made their
// controls indistinguishable to a model (iteration 21 planner views).
function groupPath(element: Element): string {
  const names: string[] = [];
  for (let node = element.closest("[data-assistant-group]"); node; node = node.parentElement?.closest("[data-assistant-group]") ?? null) {
    const name = node.getAttribute("data-assistant-group");
    if (name && names[0] !== name) names.unshift(name);
  }
  return names.join(" / ");
}

// A control the user cannot see is not a control the assistant may read, with
// one deliberate exception: the appearance panel that the user keeps closed is
// still mounted offscreen so styling works without touching their advanced
// toggle. Only that host is skipped; anything hidden inside it still counts,
// as does anything hiding the host itself from above (a modal, for instance).
function assistantHidden(element: HTMLElement): boolean {
  const host = element.closest('[data-assistant-offscreen="true"]');
  for (let node: HTMLElement | null = element; node; node = node.parentElement) {
    if (node === host) continue;
    if (node.hasAttribute("inert") || node.hasAttribute("hidden") || node.getAttribute("aria-hidden") === "true") return true;
  }
  return false;
}

function description(element: Element): string {
  const explicit = element.getAttribute("aria-label");
  const group = groupPath(element);
  if (explicit) return [group, explicit].filter(Boolean).join(" / ");
  const label = element.labels?.[0] ?? element.closest("label") ??
    (element.previousElementSibling?.tagName === "LABEL" ? element.previousElementSibling : null);
  if (!label) return element.getAttribute("placeholder") || "";
  const copy = label.cloneNode(true) as HTMLElement;
  copy.querySelectorAll("input,select,button,option").forEach(node => node.remove());
  const caption = label.querySelector(":scope > span")?.textContent || copy.textContent || "";
  return [group, caption.replace(/\s+/g, " ").trim()].filter(Boolean).join(" / ");
}

export function useAssistantControl<T extends Element>(onChange: ((event: ChangeEvent<T>) => void) | undefined, onBlur?: (event: FocusEvent<T>) => void) {
    const enabled = useContext(AssistantControlScope);
  const instanceId = useId();
  const ref = useRef<T>(null);
  useLayoutEffect(() => {
    if (!enabled || !onChange || !ref.current) return;
    const id = `${description(ref.current).slice(0, 120)} [${instanceId}]`;
    controls.set(id, {
      commit() {
        const element = ref.current;
        if (element && onBlur) onBlur({ target: element, currentTarget: element, type: "blur" } as FocusEvent<T>);
      },
      read() {
        const element = ref.current;
        if (!element || element.disabled || (!(element instanceof HTMLSelectElement) && element.readOnly) || assistantHidden(element)) return null;
        const label = description(element);
        if (!label) return null;
        const select = element instanceof HTMLSelectElement;
        const type = select ? (element.multiple ? "multiple" : "select") : element instanceof HTMLTextAreaElement ? "text" : element.inputMode === "decimal" ? "number" : element.type;
        if (!["text", "number", "color", "checkbox", "select", "multiple"].includes(type)) return null;
        const options = select ? Array.from(element.options).filter(o => !o.disabled).map(o => o.value) : [];
        const value = select && element.multiple ? Array.from(element.selectedOptions).map(o => o.value)
          : element instanceof HTMLInputElement && type === "checkbox" ? element.checked : element.value;
        const displayControl = element.getAttribute("data-assistant-permission") === "view" ||
          /^(Protein \/ Site|Protein|Site|Protein source|Protein or gene|Proteins or genes \(comma, space, or newline\)|Conditions?|Condition [12]( Control)?|Samples?|Dataset level|Label column)$/i.test(label.replace(/^Tile \d+: [^/]+ \/ /, ""));
        const appearance = element.getAttribute("data-assistant-permission") === "view" && !!element.closest('[data-assistant-appearance="true"]');
        const optionLabels = select ? Object.fromEntries(Array.from(element.options)
          .filter(option => !option.disabled && option.label !== option.value)
          .slice(0, 80).map(option => [option.value, option.label])) : undefined;
        return { id, label, appearance, optionLabels, permission: displayControl ? "view" : "confirm", type: type as AssistantControl["type"], value, options, optionCount: options.length,
          min: element instanceof HTMLInputElement && element.min ? Number(element.min) : undefined,
          max: element instanceof HTMLInputElement && element.max ? Number(element.max) : undefined };
      },
      apply(value) {
        const element = ref.current!;
        if (element instanceof HTMLSelectElement && Array.isArray(value)) {
          Array.from(element.options).forEach(option => { option.selected = value.includes(option.value); });
        } else if (element instanceof HTMLInputElement && typeof value === "boolean") {
          element.checked = value;
        } else element.value = String(value);
        // These registered controls consume target/currentTarget, just as on manual input.
        onChange({ target: element, currentTarget: element, type: "change" } as ChangeEvent<T>);
      },
    });
    return () => { controls.delete(id); };
  });
  return ref;
}

// Settings of the data pipeline -- how data are filtered, normalized, imputed or
// transformed, and the session-wide phosphosite localization cutoff -- are never
// offered to the assistant and never set by it, at any level, with or without
// approval. The backend enforces the same rule (assistant_safety.py).
export const PIPELINE_CONTROL = /\b(?:normali[sz]\w*|imput\w*|filter\w*|transform\w*|localization probability|valid values?)\b/i;

export function isPipelineControl(label: string): boolean {
  return PIPELINE_CONTROL.test(label);
}

export function readAssistantControls(question = "", searches: Record<string, string> = {}): AssistantControl[] {
  // Identifiers are short and end sentences: "K7." must still surface K7 and
  // K70-K79 among the 40 advertised options.
  const words = question.toLowerCase().split(/\s+/).map(word => word.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, ""))
    .filter(word => word.length > 2 || (word.length > 1 && /\d/.test(word)));
  return [...controls.values(), ...buttons.values()].flatMap(binding => {
    const control = binding.read();
    if (!control || isPipelineControl(control.label)) return [];
    if (!["select", "multiple"].includes(control.type)) return [control];
    const optionText = (option: string) => `${option} ${control.optionLabels?.[option] ?? ""}`.toLowerCase();
    if (searches[control.id] !== undefined) {
      const query = searches[control.id].trim().toLowerCase();
      const matches = control.options.filter(option => optionText(option).includes(query))
        .sort((a, b) => Number(b.toLowerCase() === query) - Number(a.toLowerCase() === query));
      return [{ ...control, options: matches.slice(0, 40), optionQuery: searches[control.id], optionMatchCount: matches.length }];
    }
    const relevant = control.options.filter(option => words.some(word => optionText(option).includes(word)));
    const selected = Array.isArray(control.value) ? control.value : [String(control.value)];
    return [{ ...control, options: Array.from(new Set([...selected, ...relevant, ...control.options])).slice(0, 40) }];
  }).sort((a, b) => Number(searches[b.id] !== undefined) - Number(searches[a.id] !== undefined)
    || Number(words.some(w => b.label.toLowerCase().includes(w))) - Number(words.some(w => a.label.toLowerCase().includes(w)))
    // The appearance panel is registered even while the user keeps it closed,
    // so its ~100 settings could push a selection control past the transport
    // cap. Cosmetics the question does not name yield to the analysis controls.
    || Number(!!a.appearance) - Number(!!b.appearance)
    || a.id.localeCompare(b.id)).slice(0, 100);
}

export function searchAssistantOptions(target: string, value: ControlValue): string {
  const control = controls.get(target)?.read();
  if (!control || !["select", "multiple"].includes(control.type) || typeof value !== "string" || !value.trim() || value.length > 120) {
    throw new Error("Choose a current selection control and a short search phrase.");
  }
  return value.trim();
}

export function assistantFeatureChoices(target: string, query: string, message = ""): string {
  const control = controls.get(target)?.read();
  if (!control || control.type !== "select" || !/^(Protein \/ Site|Protein|Site|Protein or gene)$/.test(
    control.label.replace(/^Tile \d+: [^/]+ \/ /, ""))) return "";
  const normalized = query.trim().toLowerCase();
  // "starts with K7" asks for the prefix matches, and an exact K7 among them
  // must not hide K70-K79 (held-out iteration 20).
  const prefix = /\b(?:starts?|starting|begins?|beginning)\s+with\b|\bprefix\b/i.test(message);
  const matches = [...new Set(control.options.filter(option => prefix
    ? option.toLowerCase().startsWith(normalized) : option.toLowerCase().includes(normalized)))];
  if (matches.length < 2 || (!prefix && matches.some(option => option.toLowerCase() === normalized))) return "";
  return `Which uploaded identifier do you mean for ${control.label}? ${matches.length} matches: ` +
    matches.slice(0, 5).map(option => JSON.stringify(option)).join(", ") +
    (matches.length > 5 ? ". Showing the first 5; provide an exact identifier or narrow the search." : ". Please provide the exact identifier.") +
    " No feature was selected by this search.";
}

export function useAssistantCanvasButton(onClick: (() => void) | undefined, effect: "add" | "remove") {
  const enabled = useContext(AssistantControlScope);
  const instanceId = useId();
  const ref = useRef<HTMLButtonElement>(null);
  useLayoutEffect(() => {
    if (!enabled || !onClick || !ref.current) return;
    const group = ref.current.closest("[data-assistant-group]")?.getAttribute("data-assistant-group");
    const id = `${[group, ref.current.textContent?.trim()].filter(Boolean).join(" / ").slice(0, 120)} [${instanceId}]`;
    const read = (): AssistantControl | null => {
      const element = ref.current;
      if (!element || element.disabled || element.closest("[inert],[hidden],[aria-hidden=true]")) return null;
      const group = element.closest("[data-assistant-group]")?.getAttribute("data-assistant-group");
      return { id, label: [group, element.textContent?.trim()].filter(Boolean).join(" / "),
        type: "button", permission: effect === "remove" ? "confirm" : "view", value: "", options: [], optionCount: 0 };
    };
    buttons.set(id, { read, activate() {
      const control = read();
      if (!control) throw new Error("This canvas action is no longer available.");
      const tileId = ref.current?.closest("[data-assistant-tile]")?.getAttribute("data-assistant-tile");
      const before = Array.from(document.querySelectorAll("[data-assistant-tile]")).map(el => el.getAttribute("data-assistant-tile"));
      flushSync(onClick);
      const after = Array.from(document.querySelectorAll("[data-assistant-tile]")).map(el => el.getAttribute("data-assistant-tile"));
      const accepted = effect === "add" ? after.length === before.length + 1 && before.every(id => after.includes(id))
        : tileId && before.includes(tileId) && after.length === before.length - 1 && !after.includes(tileId);
      if (!accepted) throw new Error("The canvas did not confirm the requested tile change. Check the current canvas.");
      return `${control.label}: completed.`;
    } });
    return () => { buttons.delete(id); };
  });
  return ref;
}

export function assistantButtonConfirmation(target: string): string {
  const control = buttons.get(target)?.read();
  if (!control) throw new Error("This canvas action is no longer available.");
  return control.permission === "confirm" ? `Remove this canvas tile? ${control.label}` : "";
}

export function activateAssistantButton(target: string, approval: string): string {
  if (assistantButtonConfirmation(target) !== approval) throw new Error("The canvas action changed before approval.");
  return buttons.get(target)!.activate();
}

export function addCanvasTiles(value: ControlValue, remaining: number, onApplied: (receipt: string) => void): string {
  const labels: Record<string, string> = { volcano: "Volcano", volcanoControl: "Volcano Control",
    proteinBoxplot: "Protein Boxplot", proteinLineplot: "Protein Lineplot", oraList: "GO Enrichment (ORA, List)" };
  const request = typeof value === "string" ? JSON.parse(value) : null;
  if (!request || Object.keys(request).sort().join() !== "count,type" || typeof request.type !== "string" ||
      !Object.hasOwn(labels, request.type) || !Number.isInteger(request.count) || request.count < 1 || request.count > Math.min(8, remaining)) {
    throw new Error("Choose an existing canvas plot type and a count within the remaining action budget.");
  }
  const tiles = () => new Map(Array.from(document.querySelectorAll("[data-assistant-tile]")).map(el =>
    [el.getAttribute("data-assistant-tile"), el.getAttribute("data-assistant-tile-type")]));
  for (let index = 0; index < request.count; index++) {
    const selectors = [...controls.values()].map(binding => binding.read()).filter(control =>
      control?.label === "New tile type" && control.type === "select" && control.permission === "view");
    if (selectors.length !== 1) throw new Error("The canvas plot-type selector is unavailable.");
    applyAssistantControls([{ type: "set_control", target: selectors[0]!.id, value: request.type }]);
    const addButtons = [...buttons.values()].map(binding => binding.read()).filter(control =>
      control?.label === "+ Add Plot" && control.permission === "view");
    if (addButtons.length !== 1) throw new Error("The canvas add button is unavailable.");
    const before = tiles();
    activateAssistantButton(addButtons[0]!.id, "");
    const after = tiles();
    const added = [...after].filter(([id]) => !before.has(id));
    if (after.size !== before.size + 1 || added.length !== 1 || added[0][1] !== request.type ||
        [...before].some(([id, type]) => after.get(id) !== type)) {
      throw new Error("The canvas did not confirm the requested plot type. Check the current tiles before retrying.");
    }
    onApplied(`Added ${labels[request.type]} tile (${index + 1}/${request.count}).`);
  }
  return `Added ${request.count} ${labels[request.type]} ${request.count === 1 ? "tile" : "tiles"}. Existing plots were kept.`;
}

function validate(control: AssistantControl, value: ControlValue) {
  if (control.type === "checkbox") {
    if (typeof value !== "boolean") throw new Error(`${control.label} requires true or false.`);
  } else if (control.type === "multiple") {
    if (!Array.isArray(value) || value.some(v => !control.options.includes(v))) throw new Error(`Unknown selection for ${control.label}.`);
  } else {
    if (typeof value !== "string" || value.length > 1000) throw new Error(`Invalid value for ${control.label}.`);
    if (control.type === "select" && !control.options.includes(value)) throw new Error(`Unknown option for ${control.label}: ${value}`);
    if (control.type === "color" && !/^#[0-9a-f]{6}$/i.test(value)) throw new Error("Use a six-digit hex color.");
    if (control.type === "number" && (!value.trim() || !Number.isFinite(Number(value)) ||
        (control.min !== undefined && Number(value) < control.min) || (control.max !== undefined && Number(value) > control.max))) {
      throw new Error(`Value outside the allowed range for ${control.label}.`);
    }
  }
}

export function assistantConfirmation(actions: AssistantAction[]): string[] {
  return actions.flatMap(action => {
    const control = controls.get(action.target)?.read();
    if (action.type !== "set_control" || !control) throw new Error("The plot controls changed. Please retry.");
    validate(control, action.value);
    return control.permission === "confirm" && JSON.stringify(control.value) !== JSON.stringify(action.value)
      ? [`${control.label}: ${JSON.stringify(control.value)} → ${JSON.stringify(action.value)}`] : [];
  });
}

// The name a select shows for the value a receipt records ("unpaired_welch" is shown as the
// option the user sees); receipts stay exact for the planner, the chat shows the name.
export const receiptDisplayValues = new Map<string, string>();

export function applyAssistantControls(actions: AssistantAction[], onApplied: (receipt: string) => void = () => {}, approvedChanges: string[] = []): string[] {
  if (new Set(actions.map(action => action.target)).size !== actions.length) {
    throw new Error("A control may be set only once per batch. No changes from this batch were applied.");
  }
  if (assistantConfirmation(actions).some(change => !approvedChanges.includes(change))) {
    throw new Error("This scientific view change requires your confirmation.");
  }
  for (const action of actions) {
    const control = controls.get(action.target)?.read();
    if (action.type !== "set_control" || !control) throw new Error("The plot controls changed. Please retry.");
    if (isPipelineControl(control.label)) {
      throw new Error("The assistant never changes how data are filtered, normalized, imputed or transformed. Nothing was changed.");
    }
    validate(control, action.value);
  }
  const receipts: string[] = [];
  for (const action of actions) {
    const binding = controls.get(action.target);
    const control = binding?.read();
    if (!binding || !control) throw new Error(`Controls changed after: ${receipts.join("; ") || "no changes"}. Please retry.`);
    if (assistantConfirmation([action]).some(change => !approvedChanges.includes(change))) {
      throw new Error("The scientific setting changed after approval. Please retry.");
    }
    validate(control, action.value);
    flushSync(() => binding.apply(action.value));
    flushSync(() => controls.get(action.target)?.commit());
    const actual = controls.get(action.target)?.read();
    if (actual && JSON.stringify(actual.value) !== JSON.stringify(control.value)) {
      recordAssistantChange({ target: action.target, label: control.label, before: control.value, after: actual.value });
      const receipt = `Set ${control.label} to ${JSON.stringify(actual.value)}.`;
      const shown = typeof actual.value === "string" ? actual.optionLabels?.[actual.value] : undefined;
      if (shown && shown !== actual.value) receiptDisplayValues.set(receipt, shown);
      receipts.push(receipt);
      onApplied(receipt);
    }
    const sameSelection = actual && Array.isArray(actual.value) && Array.isArray(action.value) &&
      JSON.stringify([...new Set(actual.value)].sort()) === JSON.stringify([...new Set(action.value)].sort());
    const accepted = actual && (sameSelection || JSON.stringify(actual.value) === JSON.stringify(action.value) ||
      (actual.type === "number" && Number(actual.value) === Number(action.value)));
    if (!accepted) {
      throw new Error(`${control.label} did not accept the requested value. Check the plot controls.`);
    }
    if (actual && JSON.stringify(actual.value) === JSON.stringify(control.value)) {
      const receipt = `${control.label} was already ${JSON.stringify(actual.value)}.`;
      receipts.push(receipt);
      onApplied(receipt);
    }
  }
  return receipts;
}
