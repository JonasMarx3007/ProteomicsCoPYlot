// @vitest-environment node
/**
 * What the assistant remembers between turns.
 *
 * Only selections it observed on screen and the explicit status of the last
 * task are kept, bounded in size, and dropped as soon as the data changes. A
 * secret typed into a field, or a conclusion the model generated, is never
 * carried into the next request.
 *
 * Converted from a node --test file that transpiled the module by hand.
 */
import { expect, it } from "vitest";
import { AssistantConversation } from "../../src/lib/assistantConversation";
import type { AssistantView } from "../../src/lib/api";

const view = {
  module: "singleProtein.boxplot", workflow: "protein", mode: {}, destinations: {}, controls: [
    { label: "Protein / Site", value: "P53" }, { label: "Condition 1", value: "A" },
    { label: "API key", value: "do-not-retain" }, { label: "Invented result", value: "do-not-retain" },
  ],
} as unknown as AssistantView;

it("retains only observed selection fields and explicit task state", () => {
  const memory = new AssistantConversation();
  memory.record(2, "Show this protein", view, ["Opened boxplot."], "interrupted");
  expect(memory.read(2)!.selections).toEqual([{ label: "Protein / Site", value: "P53" }, { label: "Condition 1", value: "A" }]);
  expect(memory.read(2)!.status).toBe("interrupted");
  expect(JSON.stringify(memory.read(2))).not.toContain("do-not-retain");
});

it("drops conversational selections on a data revision change and on an explicit reset", () => {
  const memory = new AssistantConversation();
  memory.record(2, "Show this protein", view, [], "completed");
  expect(memory.read(3)).toBeNull();
  memory.record(3, "Show this protein", view, [], "completed");
  memory.clear();
  expect(memory.read(3)).toBeNull();
});

it("bounds the size of what it keeps", () => {
  const memory = new AssistantConversation();
  memory.record(1, "q".repeat(10000), { ...view, controls: [{ label: "Protein", value: "x".repeat(10000) }] } as unknown as AssistantView,
    ["r".repeat(10000)], "declined");
  expect(memory.read(1)!.request.length).toBe(1000);
  expect(memory.read(1)!.completed[0].length).toBe(200);
  expect(memory.read(1)!.selections).toEqual([]);
});

it("keeps observed UI receipts of an incomplete answer, not generated conclusions", () => {
  const memory = new AssistantConversation();
  memory.record(1, "Open the plot and explain it", view, ["Opened boxplot."], "incomplete");
  expect(memory.read(1)!.status).toBe("incomplete");
  expect(memory.read(1)!.completed).toEqual(["Opened boxplot."]);
  expect(memory.read(2)).toBeNull();
});
