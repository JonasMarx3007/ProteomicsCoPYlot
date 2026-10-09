import { flushSync } from "react-dom";
import { assistantStep, CloudAiConsentRequiredError, getAssistantProgress, hasPendingUiRequests, type AssistantView, type AssistantResult } from "./api";
import { applyAssistantControls, receiptDisplayValues, assistantConfirmation, readAssistantControls, assistantSurfaceReady, searchAssistantOptions, assistantButtonConfirmation, activateAssistantButton, addCanvasTiles, assistantFeatureChoices } from "./assistantControls";
import { stableSnapshot, unsavedAnalysis } from "./unsavedAnalysis";
import { AssistantConversation } from "./assistantConversation";
import { focusCanvas } from "./canvasFocus";
import { applyStyle, saveStyle } from "./plotStyles";

// Control receipts are written for the planner ("Set <label> to <json>.") so a
// completed change can be matched exactly. That wording is machine-facing: in
// round 35 the chat showed 'Set X axis / X tick label size to "8.0".', a
// control path and a value the user never used. Every receipt is rewritten here
// as the sentence a person would say, with the exact value kept.
const CONTAINERS = ["Names and colors", "Frame and grid", "Boxes and their points"];

function settingName(label: string): string {
  if (label === "Title / Text") return "plot title";
  let parts = label.split(" / ").filter(part => !CONTAINERS.includes(part));
  if (parts[0] === "Font" && parts.length > 1) return `font for ${parts.slice(1).join(" ").toLowerCase()}`;
  const axis = /^([XY]) axis$/.exec(parts[0] ?? "");
  if (axis) {
    parts = [`${axis[1].toLowerCase()}-axis`, ...parts.slice(1).map(part =>
      part.replace(/^[XY] (tick)/i, "$1").replace(/^Axis label$/, "label"))];
  }
  const words = parts.map(part => part.replace(/^Show /, "").replace(/\s*\([^)]*\)/, ""))
    .map(part => /^[A-Z0-9]{2,}$/.test(part) ? part : part.toLowerCase()).join(" ");
  return words.replace(/\b(\w+) \1\b/g, "$1");
}

export function readableReceipt(receipt: string): string {
  const already = /^(.+) was already (.+)\.$/.exec(receipt);
  const change = already ?? /^Set (.+) to (.+)\.$/.exec(receipt);
  if (!change) return receipt;
  const [, rawLabel, raw] = change;
  let value: unknown;
  try { value = JSON.parse(raw); } catch { return receipt; }
  const tile = /^Tile (\d+): [^/]+ \/ (.*)$/.exec(rawLabel);
  const label = tile ? tile[2] : rawLabel;
  const scope = tile ? ` on tile ${tile[1]}` : "";
  if (label === "Protein / Site") {
    return already ? `${String(value)} was already selected${scope}.` : `Showing ${String(value)}${scope}.`;
  }
  const border = /^(?:Frame and grid \/ )?Axis frame \/ (Top|Bottom|Left|Right)$/.exec(label);
  if (border && typeof value === "boolean") {
    return `${value ? "Showed" : "Hid"} the ${border[1].toLowerCase()} border${scope}.`;
  }
  const rotation = /^([XY]) axis \/ [XY] tick label rotation$/.exec(label);
  if (rotation && !already) return `Rotated the ${rotation[1].toLowerCase()}-axis labels to ${String(value)} degrees${scope}.`;
  const item = /^(?:Names and colors \/ )?(Condition|Sample) (colors|names) \/ (.+)$/.exec(label);
  if (item) {
    const kind = `${item[1].toLowerCase()} ${JSON.stringify(item[3])}`;
    return item[2] === "colors"
      ? `Changed the color of ${kind} to ${String(value)}${scope}.`
      : `Renamed ${kind} to ${JSON.stringify(value)} for display${scope}.`;
  }
  const name = settingName(label);
  if (!name) return receipt;
  // "(cm)" is a unit; "(static plot)" says where the setting applies and is not one.
  const unit = /\((cm|mm|px|pt|%|°|degrees?)\)\s*$/i.exec(label)?.[1] ?? "";
  // "Reference line / Show", "Title / Bold": the last part is the switch, the rest is the thing
  // (2026-10-08: "Hidden the reference line show.", "Showing the title bold.").
  const parts = label.split(" / ");
  const last = parts.length > 1 ? parts[parts.length - 1] : "";
  if (typeof value === "boolean" && last) {
    const thing = settingName(parts.slice(0, -1).join(" / "));
    if (thing && /^(?:show|visible|shown|display)$/i.test(last)) {
      return already ? `The ${thing} was already ${value ? "shown" : "hidden"}${scope}.`
        : `${value ? "Showed" : "Hid"} the ${thing}${scope}.`;
    }
    if (thing && /^(?:bold|italic)$/i.test(last)) {
      const style = last.toLowerCase();
      return already ? `The ${thing} was already ${value ? "" : "not "}${style}${scope}.`
        : value ? `Made the ${thing} ${style}${scope}.` : `The ${thing} is no longer ${style}${scope}.`;
    }
  }
  if (typeof value === "boolean") {
    return already ? `The ${name} was already ${value ? "shown" : "hidden"}${scope}.`
      : `${value ? "Showed" : "Hid"} the ${name}${scope}.`;
  }
  if (Array.isArray(value)) return already ? receipt : `Changed the ${name} to ${value.join(", ")}${scope}.`;
  const shown = receiptDisplayValues.get(receipt);
  if (shown && !already) return `Changed the ${name} to ${shown}${scope}.`;
  const text = /^-?\d+(?:\.\d+)?$/.test(String(value))
    ? String(Number(value)) + (/rotation/.test(name) ? " degrees" : unit ? ` ${unit}` : "")
    : /^#[0-9a-f]{6}$/i.test(String(value)) ? String(value) : JSON.stringify(value);
  return already ? `The ${name} was already ${text}${scope}.` : `Changed the ${name} to ${text}${scope}.`;
}

export type AssistantRunOptions = {
  // The rendered plot for Advanced models that read images; captured fresh before every step.
  plotImage?: () => Promise<string | undefined>;
  // A model that thinks before answering: tell the user a step may take a while.
  slow?: boolean;
};

// An error whose reason is already written into the chat transcript.
export class ShownAssistantError extends Error {
  readonly shownInChat = true;
}

export async function runAssistant(
  payload: Omit<Parameters<typeof assistantStep>[0], "view" | "receipts" | "notes" | "answerOnly">,
  readLocation: () => Omit<AssistantView, "controls">,
  navigate: (destination: string) => void,
  progress: (text: string) => void,
  signal: AbortSignal,
  conversation: AssistantConversation = new AssistantConversation(),
  options: AssistantRunOptions = {},
): Promise<AssistantResult> {
  const receipts: string[] = [];
  // Changes allowed in this request; the backend sets it from the model's
  // assistant level (8 for Basic and Standard, more for Advanced).
  let budget = 8;
  let reviewing = false;
  let reviewed = false;
  // Requested changes the application left out (wrong scope, unavailable):
  // shown in the final answer and sent back so the planner does not retry them.
  const notes: string[] = [];
  const note = (text: string) => { if (text && !notes.includes(text) && notes.length < 8) notes.push(text); };
  const searches: Record<string, string> = {};
  const activatedButtons = new Set<string>();
  const attemptedSteps = new Set<string>();
  const attemptedSearches = new Set<string>();
  let previousActions: AssistantResult["actions"] = [];
  let explanationPending = false;
  let stoppedEarly = false;
  let stopReason = "";
  let answerOnly = false;
  // An explanation requested after a change (a focused canvas, a new test)
  // reads results that may still be loading. Re-asking once the view has
  // settled is safe -- an explanation applies nothing -- where proceeding on a
  // view that moved underneath the request is not. Bounded, so a view that
  // never settles still ends with the error.
  let settleRetries = 0;
  // A repeated step is recognised by what it does, not by React's per-mount
  // control ids: a remounted tab gets new ids for the same controls, and the
  // loop guard used to miss the repetition (iteration 20 navigation loops).
  const labels = new Map<string, string>();
  const stepIdentity = (view: AssistantView, actions: AssistantResult["actions"]) => {
    view.controls.forEach(control => labels.set(control.id, control.label));
    const name = (id: string) => labels.get(id) ?? id;
    return stableSnapshot({
      view: { ...view, controls: view.controls.map(({ id, ...rest }) => ({ ...rest, id: name(id) })) },
      actions: actions.map(action => ({ ...action, target: name(action.target) })),
    });
  };
  const revision = unsavedAnalysis.capture(null);
  if (revision.pending) throw new Error("Wait for the analysis update to finish before asking the assistant.");
  const readView = (): AssistantView => ({ ...readLocation(), controls: readAssistantControls(payload.message, searches) });
  const checkAbort = () => { if (signal.aborted) throw new DOMException("Aborted", "AbortError"); };
  let previousConversation = conversation.read(revision.revision);
  const remember = (status: Parameters<AssistantConversation["record"]>[4]) => {
    const now = unsavedAnalysis.capture(null);
    if (now.pending || now.revision !== revision.revision) conversation.clear();
    else conversation.record(revision.revision, payload.message, readView(), receipts, status);
  };
  const stopRepeatedStep = (result: AssistantResult, search = false): AssistantResult => {
    remember("needs_clarification");
    const changes = receipts.filter(receipt => !receipt.startsWith("Searched selection options"));
    const question = search
      ? "That search has already been checked. Please choose an exact identifier or narrow the search."
      : "I stopped a repeated step and kept the completed changes. Which remaining change should I make?";
    return { ...result, actions: [], needsClarification: true, usedEvidenceFallback: false, explainAfterChanges: false,
      answer: [...changes.map(readableReceipt), ...notes, question, ...(explanationPending ? ["The requested explanation is still pending."] : [])].join("\n\n"),
      evidence: receipts.length ? [{ tool: "Assistant steps", status: "available", text: receipts.join("\n") }] : [] };
  };
  try {
    for (let step = 0; step < 9; step++) {
      if (step === 8 && !answerOnly) break;
      let previous = "";
      let stable = 0;
      for (let attempt = 0; attempt < 100; attempt++) {
        await new Promise(resolve => window.setTimeout(resolve, 200));
        checkAbort();
        const current = stableSnapshot(readView());
        stable = current === previous ? stable + 1 : 0;
        // Before an explanation, wait a little longer for loading results.
        if (stable >= (answerOnly ? 3 : 1) && !hasPendingUiRequests() && assistantSurfaceReady(readLocation().module)) break;
        if (attempt === 99) throw new Error("The plot is still updating. Please retry once it has finished.");
        previous = current;
      }
      const view = readView();
      const snapshot = stableSnapshot(view);
      if (previousActions.length) attemptedSteps.add(stepIdentity(view, previousActions));
      const beforeRequest = unsavedAnalysis.capture(null);
      if (beforeRequest.pending || beforeRequest.revision !== revision.revision) {
        throw new Error("The analysis changed while I was working. Please retry.");
      }
      progress([...receipts.map(readableReceipt), ...notes, step ? "Checking the updated view…"
        : options.slow ? "Thinking about your request… a large model can take a minute or two." : "Inspecting the request…"].join("\n"));
      const plotImage = options.plotImage && !answerOnly ? await options.plotImage().catch(() => undefined) : undefined;
      checkAbort();
      // A slow model reports how far it is (thinking, tokens, seconds) while the step runs.
      const progressId = options.slow && typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : undefined;
      const waiting = [...receipts.map(readableReceipt), ...notes].join("\n");
      const poll = progressId ? window.setInterval(() => {
        void getAssistantProgress(progressId).then(state => {
          if (signal.aborted || state.phase === "unknown") return;
          const what = reviewing ? "Checking the rendered plot" : state.phase === "answering" ? "Writing the answer"
            : state.phase === "thinking" ? "Thinking" : "Waiting for the model";
          const detail = [state.tokens ? `${state.tokens} tokens` : "", `${state.seconds} s`].filter(Boolean).join(", ");
          progress([waiting, `${what}… (${detail})`].filter(Boolean).join("\n"));
        }).catch(() => {});
      }, 1500) : undefined;
      let result: AssistantResult;
      try {
        result = await assistantStep({ ...payload, messages: previousConversation ? payload.messages : [], view, receipts, notes, answerOnly,
          conversationState: previousConversation, ...(plotImage ? { plotImage } : {}), ...(progressId ? { progressId } : {}),
          ...(reviewing ? { reviewing } : {}) }, signal);
      } finally {
        if (poll !== undefined) window.clearInterval(poll);
      }
      checkAbort();
      if (typeof result.actionBudget === "number" && result.actionBudget > 0) budget = result.actionBudget;
      const now = unsavedAnalysis.capture(null);
      if (now.pending || now.revision !== revision.revision || stableSnapshot(readView()) !== snapshot) {
        if (answerOnly && !result.actions.length && !now.pending && now.revision === revision.revision && settleRetries < 3) {
          settleRetries += 1;
          step -= 1;
          continue;
        }
        throw new Error("The view or analysis changed while I was working. Please retry.");
      }
      if (answerOnly && result.actions.length) throw new Error("An explanation cannot apply further view changes.");
      if (result.needsClarification && result.actions.length) {
        throw new Error("The assistant requested clarification and changes together. No changes from this step were applied.");
      }
      explanationPending ||= result.explainAfterChanges === true;
      // A later proposal was rejected after completed changes: those changes
      // stand, the request is recorded as incomplete, not as an error.
      stoppedEarly ||= result.stoppedEarly === true;
      if (result.stoppedEarly) stopReason = result.answer;
      if (result.answer && result.actions.length && result.actions.every(action => action.type === "set_control")) note(result.answer);
      if (!result.actions.length) {
        if (explanationPending && !answerOnly && !result.needsClarification && !result.usedEvidenceFallback && !result.evidence.length) {
          if (receipts.length && !result.stoppedEarly) note(result.answer);
          answerOnly = true;
          continue;
        }
        remember(result.needsClarification ? "needs_clarification" : result.usedEvidenceFallback || stoppedEarly ? "incomplete" : "completed");
        const changes = receipts.filter(receipt => !receipt.startsWith("Searched selection options"));
        const confirmation = changes.map(readableReceipt).join("\n");
        return { ...result,
          stoppedEarly,
          evidence: receipts.length ? [...result.evidence, { tool: "Assistant steps", status: "available", text: receipts.join("\n") }] : result.evidence,
          answer: [...new Set([confirmation, ...notes, stopReason, result.answer || (receipts.length || notes.length ? "" : "No supported action was identified.")])].filter(Boolean).join("\n\n") };
      }
      const actions = result.actions;
      const repeatableButton = actions.length === 1 && actions[0].type === "activate_control";
      const stepKey = stepIdentity(view, actions);
      if (!repeatableButton && attemptedSteps.has(stepKey)) return stopRepeatedStep(result, actions[0]?.type === "search_options");
      attemptedSteps.add(stepKey);
      previousActions = repeatableButton ? [] : actions;
      if (receipts.length + actions.length > budget) {
        throw new Error("The proposed changes exceed the remaining assistant action limit. No changes from this batch were applied.");
      }
      if (actions.every(action => action.type === "set_control")) {
        const changes = assistantConfirmation(actions);
        if (changes.length && !window.confirm(`Approve these analysis-view changes? They may recalculate the results.\n\n${changes.join("\n")}\n\nUploaded data and processing settings will not be changed.`)) {
          remember("declined");
          return { ...result, actions: [], answer: [...receipts.map(readableReceipt), ...notes, "Requested changes were declined. No further actions were applied."].join("\n") };
        }
        checkAbort();
        const approvedState = unsavedAnalysis.capture(null);
        if (approvedState.pending || approvedState.revision !== revision.revision || stableSnapshot(readView()) !== snapshot) {
          throw new Error("The view changed before approval. Please retry.");
        }
        applyAssistantControls(actions, receipt => receipts.push(receipt), changes);
      } else if (actions.length === 1 && actions[0].type === "search_options") {
        const action = actions[0];
        const query = searchAssistantOptions(action.target, action.value);
        const searchKey = stableSnapshot({ module: view.module, workflow: view.workflow, mode: view.mode,
          controls: view.controls.map(({ id, value, optionCount }) => ({ id, value, optionCount })),
          target: action.target, query });
        if (attemptedSearches.has(searchKey)) return stopRepeatedStep(result, true);
        attemptedSearches.add(searchKey);
        searches[action.target] = query;
        receipts.push(`Searched selection options for ${JSON.stringify(searches[action.target])}; no view changed.`);
        const choices = assistantFeatureChoices(action.target, query, payload.message);
        if (choices) {
          remember("needs_clarification");
          return { ...result, actions: [], needsClarification: true,
            answer: [...receipts.map(readableReceipt), choices, ...(explanationPending ? ["The requested explanation is still pending."] : [])].join("\n") };
        }
      } else if (actions.length === 1 && actions[0].type === "activate_control") {
        if (view.module !== "analysis.canvas") throw new Error("Canvas actions are unavailable in this view.");
        const target = actions[0].target;
        const approval = assistantButtonConfirmation(target);
        const repeatedAddition = !approval && activatedButtons.has(target);
        const confirmation = approval || (repeatedAddition ? "The assistant already added a plot in this request. Add another plot?" : "");
        if (confirmation && !window.confirm(confirmation)) {
          remember("declined");
          return { ...result, actions: [], answer: [...receipts.map(readableReceipt), repeatedAddition ? "Another plot was declined. Existing plots were kept." : "Tile removal was declined."].join("\n") };
        }
        checkAbort();
        const approvedState = unsavedAnalysis.capture(null);
        if (stableSnapshot(readView()) !== snapshot || approvedState.pending || approvedState.revision !== revision.revision) {
          throw new Error("The view changed before approval. Please retry.");
        }
        receipts.push(activateAssistantButton(target, approval));
        activatedButtons.add(target);
      } else if (actions.length === 1 && actions[0].type === "add_canvas_tiles") {
        if (view.module !== "analysis.canvas") throw new Error("Open the canvas before adding plots.");
        const answer = addCanvasTiles(actions[0].value, budget - receipts.length, receipt => receipts.push(receipt));
        if (explanationPending) {
          answerOnly = true;
          continue;
        }
        remember("completed");
        return { ...result, actions: [], answer };
      } else if (actions.length === 1 && actions[0].type === "focus_canvas") {
        if (view.module !== "analysis.canvas") throw new Error("Open the canvas before focusing a feature.");
        let receipt = "";
        flushSync(() => { receipt = focusCanvas(actions[0].value); });
        if (result.answer) receipt = `${result.answer}\n${receipt}`;
        receipts.push(receipt);
        if (explanationPending) {
          answerOnly = true;
          continue;
        }
        remember("completed");
        return { ...result, actions: [], answer: receipt };
      } else if (actions.length === 1 && actions[0].type === "navigate") {
        const destination = actions[0].target;
        if (!(destination in view.destinations) || destination === view.module) throw new Error("The assistant did not select a new available tab.");
        if (view.module === "stats.volcano" && destination === "analysis.canvas") {
          previousConversation = {
            request: payload.message.slice(0, 1000), module: view.module, workflow: view.workflow,
            selections: view.controls.filter(control => /^Condition [12]$/.test(control.label))
              .map(({ label, value }) => ({ label, value })),
            completed: receipts.map(receipt => receipt.slice(0, 200)).slice(-8), status: "incomplete",
          };
        }
        flushSync(() => navigate(destination));
        receipts.push(`Opened ${view.destinations[destination]}.`);
      } else if (actions.length === 1 && actions[0].type === "save_style") {
        receipts.push(saveStyle(String(actions[0].value)));
      } else if (actions.length === 1 && actions[0].type === "apply_style") {
        // Only appearance settings move between plots (lib/plotStyles.ts).
        const request = JSON.parse(String(actions[0].value)) as { name?: string; scope?: "this" | "all" };
        receipts.push(applyStyle(String(request.name ?? ""), request.scope === "all" ? "all" : "this"));
      } else throw new Error("The assistant requested an unsupported action.");
      progress([...receipts.map(readableReceipt), ...notes].join("\n"));
      if (result.finished && result.reviewAfter && options.plotImage && !reviewed && !explanationPending) {
        // One look at the rendered result: the model may fix what it sees, nothing else.
        reviewed = true;
        reviewing = true;
        continue;
      }
      if (result.finished && !explanationPending) {
        // The backend marked this batch as the whole request: no further model call.
        remember("completed");
        const done = receipts.filter(receipt => !receipt.startsWith("Searched selection options")).map(readableReceipt).join("\n");
        return { ...result, actions: [], stoppedEarly,
          evidence: [...result.evidence, { tool: "Assistant steps", status: "available", text: receipts.join("\n") }],
          answer: [...new Set([done, ...notes, stopReason])].filter(Boolean).join("\n\n") };
      }
      if (receipts.length >= budget) break;
    }
    throw new Error("Reached the assistant step limit. Completed changes are listed above; ask again if anything remains.");
  } catch (error) {
    remember("interrupted");
    if ((error instanceof DOMException && error.name === "AbortError") || error instanceof CloudAiConsentRequiredError) {
      progress(receipts.length || notes.length || stopReason ? [...receipts.map(readableReceipt), ...notes, stopReason].filter(Boolean).join("\n") : "No changes applied.");
      throw error;
    }
    // The reason belongs in the conversation, where the user is reading,
    // not only in a status line (2026-10-07: "No changes applied." alone).
    const reason = error instanceof Error && error.message ? error.message : "The assistant request failed.";
    const done = [...receipts.map(readableReceipt), ...notes, stopReason].filter(Boolean);
    progress(done.length ? [...done, `I stopped here: ${reason}`].join("\n") : `No changes applied. ${reason}`);
    throw new ShownAssistantError(reason, { cause: error });
  }
}
