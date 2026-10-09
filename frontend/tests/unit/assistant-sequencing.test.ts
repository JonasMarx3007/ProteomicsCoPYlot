/**
 * How the assistant sequences a request: plan, apply, re-read, explain.
 *
 * `runAssistant` asks the planner for one step at a time, applies it only on a
 * view that has settled, stops on a repeated step instead of looping, keeps the
 * changes it completed when a later step fails, and hands a pending explanation
 * the final view. Each scenario below scripts the planner's replies and the
 * controls on screen, and checks what was sent, applied and answered.
 *
 * Converted from a node --test file that compiled runAssistant.ts with its
 * imports replaced by globals; the imports are module mocks here. The checks
 * that read the control registry live in assistant-controls.test.tsx.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/lib/api";
import type { AssistantResult } from "../../src/lib/api";
import * as controls from "../../src/lib/assistantControls";
import type { AssistantAction, AssistantControl } from "../../src/lib/assistantControls";
import { readableReceipt, runAssistant, ShownAssistantError, type AssistantRunOptions } from "../../src/lib/runAssistant";
import { unsavedAnalysis } from "../../src/lib/unsavedAnalysis";
import { registerStyleStore } from "../../src/lib/plotStyles";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));
vi.mock("../../src/lib/assistantControls", () => ({
  applyAssistantControls: vi.fn(), assistantConfirmation: vi.fn(), readAssistantControls: vi.fn(),
  assistantSurfaceReady: vi.fn(), searchAssistantOptions: vi.fn(), assistantButtonConfirmation: vi.fn(),
  activateAssistantButton: vi.fn(), addCanvasTiles: vi.fn(), assistantFeatureChoices: vi.fn(), receiptDisplayValues: new Map<string, string>(),
}));
vi.mock("../../src/lib/canvasFocus", () => ({ focusCanvas: () => "Focused the canvas." }));
vi.mock("../../src/lib/unsavedAnalysis", async (original) => ({
  ...(await original<typeof import("../../src/lib/unsavedAnalysis")>()),
  unsavedAnalysis: { capture: vi.fn() },
}));

type Reply = Partial<AssistantResult> & { error?: string; cancel?: boolean; mutate?: () => void };
type Control = Partial<AssistantControl> & Record<string, unknown>;
type Options = {
  decline?: boolean; changeBeforeRequest?: boolean; applied?: AssistantAction[]; buttonApproval?: string;
  activated?: string[]; controls?: Control[]; choices?: string; progress?: (text: string) => void;
  initialModule?: string; previousState?: unknown; runOptions?: AssistantRunOptions;
};
type Payload = Parameters<typeof api.assistantStep>[0];
// What was sent, loosely typed so a scenario can read any field of it.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Sent = Record<string, any>;

/** Run one request against scripted planner replies and a scripted screen. */
async function scenario(replies: Reply[], {
  decline = false, changeBeforeRequest = false, applied = [], buttonApproval = "Remove this canvas tile?", activated = [],
  controls: onScreen = [], choices = "", progress = () => {}, initialModule = "qc.coverage", previousState = null,
  runOptions = {},
}: Options = {}) {
  const calls: Payload[] = [];
  const remembered: string[] = [];
  let module = initialModule;
  const controller = new AbortController();
  let revision = 1;
  // The settle loop waits on window.setTimeout; a dataset change is simulated there.
  vi.spyOn(window, "setTimeout").mockImplementation(((callback: () => void) => {
    if (changeBeforeRequest) revision = 2;
    queueMicrotask(callback);
    return 0;
  }) as unknown as typeof window.setTimeout);
  vi.spyOn(window, "confirm").mockImplementation(() => !decline);
  vi.mocked(unsavedAnalysis.capture).mockImplementation(() => ({ revision, pending: 0, ui: "" }));
  vi.mocked(api.assistantStep).mockImplementation(async (payload) => {
    calls.push(structuredClone(payload));
    const reply = replies.shift();
    expect(reply, "Unexpected extra assistant request").toBeTruthy();
    if (reply!.error) throw new Error(reply!.error);
    if (reply!.cancel) controller.abort();
    if (reply!.mutate) reply!.mutate();
    return { model: "mock", revision: 1, answer: "", evidence: [], actions: [], ...reply } as AssistantResult;
  });
  vi.mocked(controls.readAssistantControls).mockImplementation((_message, searches = {}) => onScreen.map((control) => ({
    ...control,
    optionQuery: searches[control.id as string] || "",
    options: ((control.options as string[]) || []).filter((option) => !searches[control.id as string] || option.includes(searches[control.id as string])),
  })) as AssistantControl[]);
  vi.mocked(controls.assistantSurfaceReady).mockReturnValue(true);
  vi.mocked(controls.searchAssistantOptions).mockImplementation((_target, value) => value as string);
  vi.mocked(controls.assistantFeatureChoices).mockReturnValue(choices);
  vi.mocked(controls.assistantButtonConfirmation).mockReturnValue(buttonApproval);
  vi.mocked(controls.activateAssistantButton).mockImplementation((target) => { activated.push(target); return "Canvas button completed."; });
  vi.mocked(controls.assistantConfirmation).mockReturnValue(["Test: old → new"]);
  vi.mocked(controls.applyAssistantControls).mockImplementation((actions, receipt = () => {}) => {
    actions.forEach((action) => {
      applied.push(action);
      const control = onScreen.find((candidate) => candidate.id === action.target);
      if (control) control.value = action.value;
      receipt("Changed test.");
    });
    return [];
  });
  const result = await runAssistant({ message: "Open CV and explain it" },
    () => ({ module, workflow: "protein", mode: { view: module }, destinations: { "qc.cv": "CV", "analysis.canvas": "Analysis" } }),
    (target) => { module = target; }, progress, controller.signal,
    { read: () => previousState, record: (...args: unknown[]) => remembered.push(args[4] as string), clear: () => {} } as never,
    runOptions);
  return { result, calls: calls as Sent[], remembered };
}

beforeEach(() => vi.clearAllMocks());

describe("readable action confirmations", () => {
  it("keep exact values without exposing control paths", () => {

    expect(readableReceipt('Set Title / Size to "3".')).toBe('Changed the title size to 3.');
    expect(readableReceipt('Set Frame and grid / Axis frame / Top to false.')).toBe('Hid the top border.');
    expect(readableReceipt('Set Protein / Site to "AKT1".')).toBe('Showing AKT1.');
    expect(readableReceipt('Set Title / Text to "MAPK1 comparison".')).toBe('Changed the plot title to "MAPK1 comparison".');
    expect(readableReceipt('Set X axis / X tick label rotation to "30".')).toBe('Rotated the x-axis labels to 30 degrees.');
    expect(readableReceipt('Set Names and colors / Condition colors / Treated to "#cc3300".')).toBe('Changed the color of condition "Treated" to #cc3300.');
    expect(readableReceipt('Set Names and colors / Sample names / A to "First sample".')).toBe('Renamed sample "A" to "First sample" for display.');
    // Round 35: every other appearance setting reached the chat as its control path.
    expect(readableReceipt('Set X axis / X tick label size to "8.0".')).toBe('Changed the x-axis tick label size to 8.');
    expect(readableReceipt('Set DPI to "150".')).toBe('Changed the DPI to 150.');
    expect(readableReceipt('Set Width (cm) to "20".')).toBe('Changed the width to 20 cm.');
    expect(readableReceipt('Set Legend / Show legend to false.')).toBe('Hid the legend.');
    expect(readableReceipt('Set Legend / Legend frame to true.')).toBe('Showed the legend frame.');
    expect(readableReceipt('Set Reference line / Show to false.')).toBe('Hid the reference line.');
    expect(readableReceipt('Set Frame and grid / Grid lines / Show to true.')).toBe('Showed the grid lines.');
    expect(readableReceipt('Set Title / Bold to true.')).toBe('Made the title bold.');
    expect(readableReceipt('Set Volcano points / Hit label size (static plot) to "12".')).toBe('Changed the volcano points hit label size to 12.');
    controls.receiptDisplayValues.set('Set Test type to "unpaired_welch".', "Welch's t-test");
    expect(readableReceipt('Set Test type to "unpaired_welch".')).toBe("Changed the test type to Welch's t-test.");
    expect(readableReceipt('Set Font / All text to "Times New Roman".')).toBe('Changed the font for all text to "Times New Roman".');
    expect(readableReceipt('Set Tile 2: proteinBoxplot / Title / Size to "14".')).toBe('Changed the title size to 14 on tile 2.');
    expect(readableReceipt('Legend / Text size was already "9".')).toBe('The legend text size was already 9.');
    expect(readableReceipt('Set unknown to "unchanged".')).toBe('Changed the unknown to "unchanged".');
    expect(readableReceipt('Opened CV.')).toBe('Opened CV.');
  });
});

describe("runAssistant", () => {
  it('answers an ambiguous feature search with verified choices without another model call', async () => {
    const { result, calls, remembered } = await scenario([{ actions: [{ type: 'search_options', target: 'protein', value: 'AKT' }] }],
      { choices: 'Choose AKT1 or AKT2. No feature was selected by this search.' });
    expect(calls.length).toBe(1);
    expect(result.needsClarification).toBe(true);
    expect(result.actions).toEqual([]);
    expect(result.answer).toMatch(/AKT1 or AKT2/);
    expect(remembered).toEqual(['needs_clarification']);
  });

  const navigate = () => ({ explainAfterChanges: true, actions: [{ type: 'navigate', target: 'qc.cv' }] });

  it('volcano to canvas carries live comparison even after manual changes', async () => {
    const controls = [{id:'first', label:'Condition 1', type:'select', value:'Vehicle'},
                      {id:'second', label:'Condition 2', type:'select', value:'Treated'}];
    const {calls} = await scenario([{actions:[{type:'navigate', target:'analysis.canvas'}]}, {}], {
      initialModule:'stats.volcano', controls,
      previousState:{module:'stats.volcano', workflow:'protein', selections:[{label:'Condition 1',value:'Treated'}, {label:'Condition 2',value:'Vehicle'}]},
    });
    expect(calls[1].conversationState.selections).toEqual(controls.map(({label,value})=>({label,value})));
    expect(calls[1].conversationState.module).toBe('stats.volcano');
  });

  it('a repeated canvas addition requires approval and declining preserves the first tile', async () => {
    const activated = [];
    const add = { actions: [{ type: 'activate_control', target: 'add' }] };
    const { calls, result } = await scenario([
      { actions: [{ type: 'navigate', target: 'analysis.canvas' }] }, add, add,
    ], { decline: true, buttonApproval: '', activated });
    expect(activated).toEqual(['add']);
    expect(calls.length).toBe(3);
    expect(result.answer).toMatch(/Another plot was declined/);
  });

  it('an explicitly approved repeated addition remains possible', async () => {
    const activated = [];
    const add = { actions: [{ type: 'activate_control', target: 'add' }] };
    await scenario([
      { actions: [{ type: 'navigate', target: 'analysis.canvas' }] }, add, add, {},
    ], { buttonApproval: '', activated });
    expect(activated).toEqual(['add', 'add']);
  });

  it('canvas identifier recovery is disclosed alongside the applied receipt', async () => {
    const { result, calls } = await scenario([
      { actions: [{ type: 'navigate', target: 'analysis.canvas' }] },
      { answer: "Resolved 'K0.' to uploaded identifier 'K0'.", actions: [{ type: 'focus_canvas', value: '{}' }] },
    ]);
    expect(calls.length).toBe(2);
    expect(result.answer).toMatch(/Resolved 'K0\.'.*Focused the canvas/s);
  });

  it('advanced plot mode is the user\'s switch and the assistant cannot flip it', async () => {
    // Appearance settings register whether or not the panel is on screen, so the
    // assistant styles the plot directly; asking to open the panel is not an action.
    await expect(scenario([{ actions: [{ type: 'advanced_options', value: true }] }])).rejects.toThrow(/unsupported action/);
  });

  it('option discovery does not claim that view settings changed', async () => {
    const { result } = await scenario([
      { actions: [{ type: 'search_options', target: 'protein', value: 'P1' }] },
      { answer: 'Which matching protein should I select?', needsClarification: true },
    ]);
    expect(result.answer).not.toMatch(/Updated the requested view|Searched selection/);
    expect(result.evidence[0].tool).toBe('Assistant steps');
  });

  it('mixed request explains the settled new view after finishing changes', async () => {
    const { result, calls } = await scenario([navigate(), {}, { answer: 'Observed CV.', evidence: [{ tool: 'CV', status: 'available', text: 'Fresh results' }] }]);
    expect(calls.map(call => call.answerOnly)).toEqual([false, false, true]);
    expect(calls[2].view.module).toBe('qc.cv');
    expect(calls[2].view.mode).toEqual({ view: 'qc.cv' });
    expect(calls[2].receipts).toEqual(['Opened CV.']);
    expect(result.answer).toMatch(/Opened CV.*Observed CV/s);
  });

  it('canvas focus hands a pending explanation the final view and verified receipt', async () => {
    const { result, calls } = await scenario([
      { explainAfterChanges: true, actions: [{ type: 'navigate', target: 'analysis.canvas' }] },
      { actions: [{ type: 'focus_canvas', value: '{}' }] },
      { answer: 'Canvas evidence.', evidence: [{ tool: 'canvas', status: 'available', text: 'Fresh result' }] },
    ]);
    expect(calls.map(call => call.answerOnly)).toEqual([false, false, true]);
    expect(calls[2].view.module).toBe('analysis.canvas');
    expect(calls[2].receipts).toEqual(['Opened Analysis.', 'Focused the canvas.']);
    expect(result.answer).toMatch(/Focused the canvas.*Canvas evidence/s);
  });

  it('the final planning slot can hand off to one read-only explanation', async () => {
    const changes = Array.from({ length: 7 }, (_, i) => ({ explainAfterChanges: true,
      actions: [{ type: 'set_control', target: `control${i}`, value: 'new' }] }));
    const { result, calls } = await scenario([...changes, {}, { answer: 'Final evidence.', evidence: [{ tool: 'test', status: 'available', text: 'Result' }] }]);
    expect(calls.length).toBe(9);
    expect(calls[8].answerOnly).toBe(true);
    expect(calls[8].receipts.length).toBe(7);
    expect(result.answer).toMatch(/Final evidence/);
  });

  it('declining changes does not start an explanation', async () => {
    const { calls, remembered, result } = await scenario([
      { explainAfterChanges: true, actions: [{ type: 'set_control', target: 'test', value: 'new' }] },
    ], { decline: true });
    expect(calls.length).toBe(1);
    expect(remembered).toEqual(['declined']);
    expect(result.answer).toMatch(/declined/);
  });

  it('explanation phase rejects unexpected actions even from the server', async () => {
    await expect(scenario([navigate(), {}, { actions: [{ type: 'navigate', target: 'analysis.canvas' }] }])).rejects.toThrow(/cannot apply further/);
  });

  it('clarification stops rather than silently starting an explanation', async () => {
    const { calls, remembered } = await scenario([navigate(), { needsClarification: true, answer: 'Which condition?' }]);
    expect(calls.length).toBe(2);
    expect(remembered).toEqual(['needs_clarification']);
  });

  it('a conflicting clarification response cannot apply controls', async () => {
    const applied = [];
    await expect(scenario([{ needsClarification: true, answer: 'Which labels?',
      actions: [{ type: 'set_control', target: 'labels', value: '45' }] }], { applied })).rejects.toThrow(/clarification and changes together/);
    expect(applied).toEqual([]);
  });

  it('cancellation after an action does not start an explanation', async () => {
    await expect(scenario([navigate(), { cancel: true }])).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('ordinary UI requests do not add an explanation call', async () => {
    const { calls } = await scenario([{ actions: [{ type: 'navigate', target: 'qc.cv' }] }, {}]);
    expect(calls.length).toBe(2);
  });

  it('repeated navigation stops without replaying or claiming full completion', async () => {
    const { result, calls, remembered } = await scenario([navigate(), navigate()]);
    expect(calls.length).toBe(2);
    expect(remembered).toEqual(['needs_clarification']);
    expect(result.actions).toEqual([]);
    expect(result.answer).toMatch(/Opened CV.*stopped a repeated step.*explanation is still pending/s);
  });

  it('repeated search stops on the second request without claiming a selection', async () => {
    const search = { actions: [{ type: 'search_options', target: 'protein', value: 'P1' }] };
    const { result, calls, remembered } = await scenario([search, search]);
    expect(calls.length).toBe(2);
    expect(remembered).toEqual(['needs_clarification']);
    expect(result.answer).toMatch(/choose an exact identifier or narrow/);
    expect(result.answer).not.toMatch(/Updated|Set |Searched selection/);
  });

  it('alternating searches cannot evade the no-progress guard', async () => {
    const search = value => ({ actions: [{ type: 'search_options', target: 'protein', value }] });
    const { result, calls } = await scenario([search('P1'), search('P2'), search('P1')], {
      controls: [{ id: 'protein', value: '', options: ['P1', 'P2'], optionCount: 2 }],
    });
    expect(calls.length).toBe(3);
    expect(result.needsClarification).toBe(true);
  });

  it('a changed selection permits a fresh search with the same query', async () => {
    const search = { actions: [{ type: 'search_options', target: 'protein', value: 'P1' }] };
    const { result, calls } = await scenario([search,
      { actions: [{ type: 'set_control', target: 'condition', value: 'B' }] }, search, {}], {
      controls: [{ id: 'protein', value: '', options: ['P1'], optionCount: 1 }, { id: 'condition', value: 'A' }],
    });
    expect(calls.length).toBe(4);
    expect(!result.needsClarification).toBeTruthy();
  });

  it('repeated identical setters do not apply twice', async () => {
    const applied = [];
    const set = { actions: [{ type: 'set_control', target: 'test', value: 'new' }] };
    const { result } = await scenario([set, set], { applied, controls: [{ id: 'test', value: 'old' }] });
    expect(applied.length).toBe(1);
    expect(result.needsClarification).toBe(true);
  });

  it('a different next action still runs after an earlier completed action', async () => {
    const applied = [];
    const { result } = await scenario([navigate(), { actions: [{ type: 'set_control', target: 'test', value: 'new' }] },
      {}, { answer: 'Fresh explanation.', evidence: [{ tool: 'test', status: 'available', text: 'Fresh result' }] }], { applied });
    expect(applied.length).toBe(1);
    expect(result.answer).toMatch(/Fresh explanation/);
    expect(!result.needsClarification).toBeTruthy();
  });

  it('fallback records incomplete without losing completed changes or retrying', async () => {
    const { result, remembered, calls } = await scenario([navigate(), {}, {
      usedEvidenceFallback: true, answer: 'Evidence fallback.', evidence: [],
    }]);
    expect(remembered).toEqual(['incomplete']);
    expect(calls.length).toBe(3);
    expect(result.answer).toMatch(/Opened CV.*Evidence fallback/s);
    expect(result.evidence.at(-1).text).toBe('Opened CV.');
  });

  it('dataset changes while waiting prevent even the next assistant request', async () => {
    await expect(scenario([], { changeBeforeRequest: true })).rejects.toThrow(/analysis changed/);
  });

  it('a batch cannot exceed the remaining total action budget', async () => {
    const applied = [];
    const batch = size => ({ actions: Array.from({ length: size }, (_, i) => ({ type: 'set_control', target: `control${i}`, value: 'new' })) });
    await expect(scenario([batch(4), batch(3), batch(2)], { applied })).rejects.toThrow(/exceed the remaining.*No changes from this batch/);
    expect(applied.length).toBe(7);
  });


  it('an explanation re-asks once a view that moved during the request has settled', async () => {
    const controls = [{ id: 'tile', label: 'Tile 1: volcano / Condition 1', value: 'loading' }];
    const settle = () => { controls[0].value = 'loaded'; };
    const { result, calls } = await scenario([navigate(), {},
      { mutate: settle, answer: 'Explained the half-loaded view.', evidence: [{ tool: 't', status: 'available', text: 'x' }] },
      { answer: 'Explained the loaded view.', evidence: [{ tool: 't', status: 'available', text: 'x' }] }], { controls });
    expect(calls.length).toBe(4);
    expect(calls.map(call => call.answerOnly)).toEqual([false, false, true, true]);
    expect(result.answer).toMatch(/loaded view/);
    expect(result.answer).not.toMatch(/half-loaded/);
  });

  it('a view that never settles still ends with the change error', async () => {
    const controls = [{ id: 'tile', label: 'Tile', value: 0 }];
    const churn = { mutate: () => { controls[0].value += 1; }, answer: 'Stale.', evidence: [{ tool: 't', status: 'available', text: 'x' }] };
    await expect(scenario([navigate(), {}, churn, churn, churn, churn], { controls })).rejects.toThrow(/view or analysis changed/);
  });

  it('late explanation retries do not consume the last planning slot', async () => {
    const controls = [{ id: 'width', label: 'Width', value: 0 }];
    const changes = Array.from({ length: 6 }, (_, index) => ({
      actions: [{ type: 'set_control', target: 'width', value: index + 1 }],
    }));
    const evidence = [{ tool: 't', status: 'available', text: 'x' }];
    const { result, calls } = await scenario([navigate(), ...changes, {},
      { mutate: () => { controls[0].value = 7; }, answer: 'Stale answer.', evidence },
      { answer: 'Settled answer.', evidence },
    ], { controls });
    expect(calls.length).toBe(10);
    expect(result.answer).toMatch(/Settled answer/);
    expect(result.answer).not.toMatch(/Stale answer/);
  });

  it('a setter repeated on remounted controls is still recognised as a repeat', async () => {
    const applied = [];
    // React gives a remounted control a new id; its label and value are unchanged.
    const controls = [{ get id() { return applied.length ? 'width [r2]' : 'width [r1]'; }, label: 'Width',
      get value() { return applied.length ? 'new' : 'old'; } }];
    const { result, calls } = await scenario([
      { actions: [{ type: 'set_control', target: 'width [r1]', value: 'new' }] },
      { actions: [{ type: 'set_control', target: 'width [r2]', value: 'new' }] },
    ], { applied, controls });
    expect(calls.length).toBe(2);
    expect(applied.length).toBe(1);
    expect(result.needsClarification).toBe(true);
  });

  // ---- section 38 (iteration 21 follow-up) ----------------------------------

  it('a scope note next to applied setters reaches the answer and the next planning step', async () => {
    const controls = [{ id: 'rot', label: 'X axis / X tick label rotation', type: 'number', value: '0', permission: 'view', options: [] }];
    const note = 'The request is about a sample, but Condition names / A changes a condition. No sample-level control for that is available in this view, so I left it unchanged.';
    const { result, calls } = await scenario([
      { actions: [{ type: 'set_control', target: 'rot', value: '45' }], answer: note },
      {},
    ], { controls });
    expect(calls[1].notes).toEqual([note]);
    expect(result.answer).toMatch(/Changed test\./);
    expect(result.answer).toMatch(/left it unchanged/);
    expect(result.answer).not.toMatch(/No supported action/);
  });

  it('a note survives the hand-off to the explanation step', async () => {
    const controls = [{ id: 'rot', label: 'X axis / X tick label rotation', type: 'number', value: '0', permission: 'view', options: [] }];
    const { result, calls } = await scenario([
      { explainAfterChanges: true, actions: [{ type: 'set_control', target: 'rot', value: '45' }] },
      { answer: 'The request does not name condition B, so I left Condition colors / B unchanged.' },
      { answer: 'Explanation of the rotated plot.' },
    ], { controls });
    expect(calls[2].answerOnly).toBe(true);
    expect(result.answer).toMatch(/left Condition colors \/ B unchanged/);
    expect(result.answer).toMatch(/Explanation of the rotated plot/);
  });

  it('a stop survives a full note buffer and the explanation response', async () => {
    const controls = [{ id: 'rot', label: 'Rotation', type: 'number', value: '0', permission: 'view', options: [] }];
    const changes = Array.from({ length: 4 }, (_, i) => ({
      explainAfterChanges: true, actions: [{ type: 'set_control', target: 'rot', value: String(i + 1) }],
      answer: `Scope note ${i + 1}.`,
    }));
    const { result, remembered } = await scenario([...changes,
      { stoppedEarly: true, explainAfterChanges: true, answer: 'Stopped with requested work still incomplete.' },
      { answer: 'Explanation of the current plot.' },
    ], { controls });
    expect(result.stoppedEarly).toBe(true);
    expect(result.answer).toMatch(/Scope note 4/);
    expect(result.answer).toMatch(/work still incomplete/);
    expect(result.answer).toMatch(/Explanation of the current plot/);
    expect(remembered).toEqual(['incomplete']);
  });

  it('scope notes and completed changes remain visible after a later provider error', async () => {
    const updates = [];
    const controls = [{ id: 'rot', label: 'Rotation', type: 'number', value: '0', permission: 'view', options: [] }];
    await expect(scenario([
      { actions: [{ type: 'set_control', target: 'rot', value: '45' }], answer: 'Sample rename was left unchanged.' },
      { error: 'Invalid subsequent plan' },
    ], { controls, progress: text => updates.push(text) })).rejects.toThrow(/Invalid subsequent plan/);
    expect(updates.at(-1)).toMatch(/Changed test/);
    expect(updates.at(-1)).toMatch(/Sample rename was left unchanged/);
  });

  // ---- section 40 (iteration 22 follow-up) ----------------------------------

  it('a rejected later proposal ends with the completed changes and an incomplete status', async () => {
    const controls = [{ id: 'rot', label: 'X axis / X tick label rotation', type: 'number', value: '0', permission: 'view', options: [] }];
    const stop = 'I made the changes above and stopped there: Invalid value for Dataset level. Nothing else was changed, so ask again for anything still missing.';
    const { result, remembered } = await scenario([
      { actions: [{ type: 'set_control', target: 'rot', value: '45' }] },
      { stoppedEarly: true, answer: stop },
    ], { controls });
    expect(result.answer).toMatch(/Changed test\./);
    expect(result.answer).toMatch(/I made the changes above and stopped there/);
    expect(remembered).toEqual(['incomplete']);
  });

  it('an explanation still follows a clean stop when one was requested', async () => {
    const controls = [{ id: 'rot', label: 'X axis / X tick label rotation', type: 'number', value: '0', permission: 'view', options: [] }];
    const { result, calls } = await scenario([
      { explainAfterChanges: true, actions: [{ type: 'set_control', target: 'rot', value: '45' }] },
      { stoppedEarly: true, explainAfterChanges: true, answer: 'I made the changes above and stopped there.' },
      { answer: 'Explanation of the rotated plot.' },
    ], { controls });
    expect(calls[2].answerOnly).toBe(true);
    expect(result.answer).toMatch(/I made the changes above and stopped there/);
    expect(result.answer).toMatch(/Explanation of the rotated plot/);
  });
});


describe("assistant levels in the request loop", () => {
  it("writes the reason into the conversation when nothing could be changed", async () => {
    const shown: string[] = [];
    const run = scenario([{ error: "The model used its whole reply budget (1024 tokens) before it finished." }],
      { progress: (text) => shown.push(text) });
    await expect(run).rejects.toBeInstanceOf(ShownAssistantError);
    expect(shown.at(-1)).toBe("No changes applied. The model used its whole reply budget (1024 tokens) before it finished.");
  });

  it("uses the budget the backend grants an Advanced model", async () => {
    const actions = Array.from({ length: 12 }, (_, index) => ({ type: "set_control" as const, target: `c${index}`, value: "1" }));
    const applied: AssistantAction[] = [];
    const { result } = await scenario([{ actions, actionBudget: 40 }, { actions: [] }],
      { applied, controls: actions.map(({ target }) => ({ id: target, label: target, type: "number", value: "0" })) });
    expect(applied).toHaveLength(12);
    expect(result.answer).not.toContain("action limit");
  });

  it("stops after a batch the backend marks as finished, without another model call", async () => {
    const applied: AssistantAction[] = [];
    const { result, calls } = await scenario([{ actions: [{ type: "set_control", target: "c1", value: "1" }], finished: true,
      answer: "Applied Nature's figure specifications." }],
      { applied, controls: [{ id: "c1", label: "Title / Size", type: "number", value: "0" }] });
    expect(calls).toHaveLength(1);
    expect(applied).toHaveLength(1);
    expect(result.answer).toContain("Applied Nature's figure specifications.");
  });

  it("lets a model that reads images review its batch once, then stops", async () => {
    const applied: AssistantAction[] = [];
    const plotImage = vi.fn(async () => "data:image/png;base64,AAAA");
    const { calls } = await scenario([
      { actions: [{ type: "set_control", target: "c1", value: "14" }], finished: true, reviewAfter: true },
      { actions: [{ type: "set_control", target: "c2", value: "8" }], finished: true },
    ], { applied, runOptions: { plotImage }, controls: [
      { id: "c1", label: "Title / Size", type: "number", value: "10" },
      { id: "c2", label: "X axis / X tick label size", type: "number", value: "10" }] });
    expect(calls).toHaveLength(2);
    expect(calls[0].reviewing).toBeUndefined();
    expect(calls[1].reviewing).toBe(true);
    expect(applied.map(action => action.target)).toEqual(["c1", "c2"]);
  });

  it("saves a style without a model plan step", async () => {
    window.sessionStorage.clear();
    const unregister = registerStyleStore("app", { active: () => ({ fontFamily: "helvetica" }), setActive: () => {}, setAll: () => 0 });
    const { result, calls } = await scenario([{ actions: [{ type: "save_style", target: "", value: "lab" }], finished: true }]);
    unregister();
    expect(calls).toHaveLength(1);
    expect(result.answer).toContain('Saved this plot\'s look as the style "lab".');
  });

  it("sends a fresh plot image with each step when the model reads images", async () => {
    const plotImage = vi.fn(async () => "data:image/png;base64,AAAA");
    const { calls } = await scenario([{ actions: [{ type: "navigate", target: "qc.cv" }] }, { actions: [] }],
      { runOptions: { plotImage, slow: true } });
    expect(plotImage).toHaveBeenCalledTimes(2);
    expect(calls.every((call) => call.plotImage === "data:image/png;base64,AAAA")).toBe(true);
  });
});
