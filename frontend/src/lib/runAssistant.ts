import { flushSync } from "react-dom";
import { assistantStep, hasPendingUiRequests, type AssistantView, type AssistantResult } from "./api";
import { applyAssistantControls, assistantConfirmation, readAssistantControls, assistantSurfaceReady, searchAssistantOptions, assistantButtonConfirmation, activateAssistantButton, addCanvasTiles, assistantFeatureChoices } from "./assistantControls";
import { getAdvancedPlotMode, setAdvancedPlotMode } from "./appSettings";
import { stableSnapshot, unsavedAnalysis } from "./unsavedAnalysis";
import { AssistantConversation } from "./assistantConversation";
import { focusCanvas } from "./canvasFocus";

export async function runAssistant(
  payload: Omit<Parameters<typeof assistantStep>[0], "view" | "receipts" | "answerOnly">,
  readLocation: () => Omit<AssistantView, "controls">,
  navigate: (destination: string) => void,
  progress: (text: string) => void,
  signal: AbortSignal,
  conversation: AssistantConversation = new AssistantConversation(),
): Promise<AssistantResult> {
  const receipts: string[] = [];
  const searches: Record<string, string> = {};
  const activatedButtons = new Set<string>();
  const attemptedSteps = new Set<string>();
  const attemptedSearches = new Set<string>();
  let previousActions: AssistantResult["actions"] = [];
  let explanationPending = false;
  let answerOnly = false;
  const revision = unsavedAnalysis.capture(null);
  if (revision.pending) throw new Error("Wait for the analysis update to finish before asking the assistant.");
  const readView = (): AssistantView => ({ ...readLocation(), advancedOptions: getAdvancedPlotMode(), controls: readAssistantControls(payload.message, searches) });
  const checkAbort = () => { if (signal.aborted) throw new DOMException("Aborted", "AbortError"); };
  const previousConversation = conversation.read(revision.revision);
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
      answer: [...changes, question, ...(explanationPending ? ["The requested explanation is still pending."] : [])].join("\n\n"),
      evidence: receipts.length ? [{ tool: "Assistant steps", status: "available", text: receipts.join("\n") }] : [] };
  };
  try {
    for (let step = 0; step < 9; step++) {
      if (step === 8 && !answerOnly) break;
      let previous = "";
      for (let attempt = 0; attempt < 100; attempt++) {
        await new Promise(resolve => window.setTimeout(resolve, 200));
        checkAbort();
        const current = stableSnapshot(readView());
        if (current === previous && !hasPendingUiRequests() && assistantSurfaceReady(readLocation().module)) break;
        if (attempt === 99) throw new Error("The plot is still updating. Please retry once it has finished.");
        previous = current;
      }
      const view = readView();
      const snapshot = stableSnapshot(view);
      if (previousActions.length) attemptedSteps.add(stableSnapshot({ view, actions: previousActions }));
      const beforeRequest = unsavedAnalysis.capture(null);
      if (beforeRequest.pending || beforeRequest.revision !== revision.revision) {
        throw new Error("The analysis changed while I was working. Please retry.");
      }
      progress([...receipts, step ? "Checking the updated view…" : "Inspecting the request…"].join("\n"));
      const result = await assistantStep({ ...payload, messages: previousConversation ? payload.messages : [], view, receipts, answerOnly, conversationState: previousConversation }, signal);
      checkAbort();
      const now = unsavedAnalysis.capture(null);
      if (now.pending || now.revision !== revision.revision || stableSnapshot(readView()) !== snapshot) {
        throw new Error("The view or analysis changed while I was working. Please retry.");
      }
      if (answerOnly && result.actions.length) throw new Error("An explanation cannot apply further view changes.");
      if (result.needsClarification && result.actions.length) {
        throw new Error("The assistant requested clarification and changes together. No changes from this step were applied.");
      }
      explanationPending ||= result.explainAfterChanges === true;
      if (!result.actions.length) {
        if (explanationPending && !answerOnly && !result.needsClarification && !result.usedEvidenceFallback && !result.evidence.length) {
          answerOnly = true;
          continue;
        }
        remember(result.needsClarification ? "needs_clarification" : result.usedEvidenceFallback ? "incomplete" : "completed");
        const changes = receipts.filter(receipt => !receipt.startsWith("Searched selection options"));
        const confirmation = changes.length > 2 ? "Updated the requested view settings." : changes.join("\n");
        return { ...result,
          evidence: receipts.length ? [...result.evidence, { tool: "Assistant steps", status: "available", text: receipts.join("\n") }] : result.evidence,
          answer: [confirmation, result.answer || (receipts.length ? "" : "No supported action was identified.")].filter(Boolean).join("\n\n") };
      }
      const actions = result.actions;
      const repeatableButton = actions.length === 1 && actions[0].type === "activate_control";
      const stepKey = stableSnapshot({ view, actions });
      if (!repeatableButton && attemptedSteps.has(stepKey)) return stopRepeatedStep(result, actions[0]?.type === "search_options");
      attemptedSteps.add(stepKey);
      previousActions = repeatableButton ? [] : actions;
      if (receipts.length + actions.length > 8) {
        throw new Error("The proposed changes exceed the remaining assistant action limit. No changes from this batch were applied.");
      }
      if (actions.every(action => action.type === "set_control")) {
        const changes = assistantConfirmation(actions);
        if (changes.length && !window.confirm(`Approve these analysis-view changes? They may recalculate the results.\n\n${changes.join("\n")}\n\nUploaded data and processing settings will not be changed.`)) {
          remember("declined");
          return { ...result, actions: [], answer: [...receipts, "Requested changes were declined. No further actions were applied."].join("\n") };
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
        const choices = assistantFeatureChoices(action.target, query);
        if (choices) {
          remember("needs_clarification");
          return { ...result, actions: [], needsClarification: true,
            answer: [...receipts, choices, ...(explanationPending ? ["The requested explanation is still pending."] : [])].join("\n") };
        }
      } else if (actions.length === 1 && actions[0].type === "activate_control") {
        if (view.module !== "analysis.canvas") throw new Error("Canvas actions are unavailable in this view.");
        const target = actions[0].target;
        const approval = assistantButtonConfirmation(target);
        const repeatedAddition = !approval && activatedButtons.has(target);
        const confirmation = approval || (repeatedAddition ? "The assistant already added a plot in this request. Add another plot?" : "");
        if (confirmation && !window.confirm(confirmation)) {
          remember("declined");
          return { ...result, actions: [], answer: [...receipts, repeatedAddition ? "Another plot was declined. Existing plots were kept." : "Tile removal was declined."].join("\n") };
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
        const answer = addCanvasTiles(actions[0].value, 8 - receipts.length, receipt => receipts.push(receipt));
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
        flushSync(() => navigate(destination));
        receipts.push(`Opened ${view.destinations[destination]}.`);
      } else if (actions.length === 1 && actions[0].type === "advanced_options") {
        if (getAdvancedPlotMode()) throw new Error("Advanced options are already enabled. Ask for a specific visible control.");
        flushSync(() => setAdvancedPlotMode(true));
        receipts.push("Enabled advanced plot options.");
      } else throw new Error("The assistant requested an unsupported action.");
      progress(receipts.join("\n"));
      if (receipts.length >= 8) break;
    }
    throw new Error("Reached the assistant step limit. Completed changes are listed above; ask again if anything remains.");
  } catch (error) {
    remember("interrupted");
    progress(receipts.length ? receipts.join("\n") : "No changes applied.");
    throw error;
  }
}
