import type { AssistantView } from "./api";

export type ConversationState = {
  request: string;
  module: string;
  workflow: string;
  selections: { label: string; value: string | boolean | string[] }[];
  completed: string[];
  status: "completed" | "incomplete" | "interrupted" | "declined" | "needs_clarification";
};

// Session-only verified UI state; no generated conclusions or numerical result cache.
export class AssistantConversation {
  private revision = -1;
  private state: ConversationState | null = null;

  clear() { this.state = null; this.revision = -1; }

  read(revision: number): ConversationState | null {
    if (revision !== this.revision) this.clear();
    return this.state;
  }

  record(revision: number, request: string, view: AssistantView, completed: string[], status: ConversationState["status"]) {
    const selections: ConversationState["selections"] = [];
    for (const control of view.controls) {
      if (!/^(Protein \/ Site|Protein|Site|Gene|Genes \/ Proteins \/ Sites|Conditions?|Condition [12]( Control)?|Samples?|Dataset level|Identifier)$/i.test(control.label)) continue;
      const selection = { label: control.label, value: control.value };
      if (selections.length >= 12 || JSON.stringify([...selections, selection]).length > 3000) break;
      selections.push(selection);
    }
    this.revision = revision;
    this.state = { request: request.slice(0, 1000), module: view.module, workflow: view.workflow,
      selections, completed: completed.map(text => text.slice(0, 200)).slice(-8), status };
  }
}
