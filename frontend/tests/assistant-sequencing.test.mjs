import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = (await readFile(new URL('../src/lib/runAssistant.ts', import.meta.url), 'utf8'))
  .replace(/^import .*;\r?$/gm, '');
let serial = 0;

test('plot dimensions expose bounded cosmetic controls without changing other numeric permissions', async () => {
  const fields = (await readFile(new URL('../src/components/PlotFields.tsx', import.meta.url), 'utf8'))
    .replace(/^import .*;\r?$/gm, '').replace(/export function/g, 'function');
  const code = ts.transpileModule(fields, {compilerOptions: {target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React}}).outputText;
  const React = {createElement: (type, props, ...children) => ({type, props, children})};
  const {NumericField, SizeRow} = new Function('React', 'useState', 'AssistantInput', 'AssistantSelect',
    'MIN_PLOT_DIMENSION_CM', 'MAX_PLOT_DIMENSION_CM', 'MIN_PLOT_DPI', 'MAX_PLOT_DPI',
    code + '\nreturn {NumericField, SizeRow};')(React, () => [null, () => {}], 'input', 'select', 1, 60, 72, 600);
  const ordinary = NumericField({label:'Threshold', value:1, onChange:()=>{}});
  assert.equal(ordinary.props['data-assistant-appearance'], undefined);
  assert.equal(ordinary.children[1].props['data-assistant-permission'], undefined);
  const row = SizeRow({widthCm:20, heightCm:10, dpi:300});
  assert.deepEqual(row.children.map(c => [c.props.label, c.props.min, c.props.max]),
    [['Width (cm)',1,60], ['Height (cm)',1,60], ['DPI',72,600]]);
  for (const child of row.children) {
    const field = NumericField(child.props);
    assert.equal(field.props['data-assistant-appearance'], 'true');
    assert.equal(field.children[1].props['data-assistant-permission'], 'view');
    assert.equal(field.children[1].props.min, child.props.min);
    assert.equal(field.children[1].props.max, child.props.max);
  }
});

test('readable action confirmations retain exact values without exposing control paths', () => {
  const code = ts.transpileModule(source.slice(source.indexOf('const CONTAINERS'), source.indexOf('export async function runAssistant')),
    {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  const describe = new Function(code + '\nreturn readableReceipt;')();
  assert.equal(describe('Set Title / Size to "3".'), 'Changed the title size to 3.');
  assert.equal(describe('Set Frame and grid / Axis frame / Top to false.'), 'Hidden the top border.');
  assert.equal(describe('Set Protein / Site to "AKT1".'), 'Showing AKT1.');
  assert.equal(describe('Set Title / Text to "MAPK1 comparison".'), 'Changed the plot title to "MAPK1 comparison".');
  assert.equal(describe('Set X axis / X tick label rotation to "30".'), 'Rotated the x-axis labels to 30 degrees.');
  assert.equal(describe('Set Names and colours / Condition colors / Treated to "#cc3300".'), 'Changed the colour of condition "Treated" to #cc3300.');
  assert.equal(describe('Set Names and colours / Sample names / A to "First sample".'), 'Renamed sample "A" to "First sample" for display.');
  // Round 35: every other appearance setting reached the chat as its control path.
  assert.equal(describe('Set X axis / X tick label size to "8.0".'), 'Changed the x-axis tick label size to 8.');
  assert.equal(describe('Set DPI to "150".'), 'Changed the DPI to 150.');
  assert.equal(describe('Set Width (cm) to "20".'), 'Changed the width to 20 cm.');
  assert.equal(describe('Set Legend / Show legend to false.'), 'Hidden the legend.');
  assert.equal(describe('Set Legend / Legend frame to true.'), 'Showing the legend frame.');
  assert.equal(describe('Set Font / All text to "Times New Roman".'), 'Changed the font for all text to "Times New Roman".');
  assert.equal(describe('Set Tile 2: proteinBoxplot / Title / Size to "14".'), 'Changed the title size to 14 on tile 2.');
  assert.equal(describe('Legend / Text size was already "9".'), 'The legend text size was already 9.');
  assert.equal(describe('Set unknown to "unchanged".'), 'Changed the unknown to "unchanged".');
  assert.equal(describe('Opened CV.'), 'Opened CV.');
});

test('control re-registration order does not look like a changed view', async () => {
  const text = await readFile(new URL('../src/lib/assistantControls.ts', import.meta.url), 'utf8');
  const code = ts.transpileModule(text.slice(text.indexOf('export function readAssistantControls'), text.indexOf('export function searchAssistantOptions')).replace('export ', ''),
    {compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;
  const controls = new Map(['b','a'].map(id => [id,{read:()=>({id,label:'Title / Size',type:'number',value:'12'})}]));
  const read = new Function('controls','buttons',code+'\nreturn readAssistantControls;')(controls,new Map());
  const before=read();
  const binding=controls.get('b'); controls.delete('b'); controls.set('b',binding);
  assert.deepEqual(read(),before);
});

test('an unnamed cosmetic setting yields to an analysis control at the transport cap', async () => {
  const text = await readFile(new URL('../src/lib/assistantControls.ts', import.meta.url), 'utf8');
  const code = ts.transpileModule(text.slice(text.indexOf('export function readAssistantControls'), text.indexOf('export function searchAssistantOptions')).replace('export ', ''),
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const entries = [['site', { id: 'site', label: 'Protein / Site', type: 'select', value: 'K1', options: ['K1'], optionCount: 1 }],
                   ['legend', { id: 'legend', label: 'Legend / Text size', type: 'number', value: '10', appearance: true }]];
  for (let index = 0; index < 120; index++) {
    entries.unshift([`c${index}`, { id: `c${index}`, label: `Title / Setting ${index}`, type: 'number', value: '1', appearance: true }]);
  }
  const read = new Function('controls', 'buttons', code + '\nreturn readAssistantControls;')(
    new Map(entries.map(([id, control]) => [id, { read: () => control }])), new Map());
  const shown = read('Which site is selected?');
  assert.equal(shown.length, 100);
  assert.equal(shown[0].id, 'site');
  // A named cosmetic setting still comes first when the question asks for it.
  assert.equal(read('Make the legend smaller.')[0].label, 'Legend / Text size');
});

test('option discovery searches displayed names but keeps the machine value', async () => {
  const text = await readFile(new URL('../src/lib/assistantControls.ts', import.meta.url), 'utf8');
  const start = text.indexOf('export function readAssistantControls');
  const code = ts.transpileModule(text.slice(start, text.indexOf('export function searchAssistantOptions')).replace('export ', ''),
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const control = { id: 'font', label: 'Font / All text', type: 'select', value: 'helvetica', options: ['helvetica', 'times'],
    optionCount: 2, optionLabels: { helvetica: 'Helvetica / Arial', times: 'Times New Roman' } };
  const read = new Function('controls', 'buttons', code + '\nreturn readAssistantControls;')(
    new Map([['font', { read: () => control }]]), new Map());
  const [found] = read('Which fonts are available?', { font: 'new roman' });
  assert.deepEqual(found.options, ['times']);
  assert.equal(found.optionMatchCount, 1);
  assert.equal(control.value, 'helvetica');
});

test('ambiguous feature search returns verified choices without another model call', async () => {
  const { result, calls, remembered } = await scenario([{ actions: [{ type: 'search_options', target: 'protein', value: 'AKT' }] }],
    { choices: 'Choose AKT1 or AKT2. No feature was selected by this search.' });
  assert.equal(calls.length, 1);
  assert.equal(result.needsClarification, true);
  assert.deepEqual(result.actions, []);
  assert.match(result.answer, /AKT1 or AKT2/);
  assert.deepEqual(remembered, ['needs_clarification']);
});

test('feature candidates use full live options but never guess exact or multi selections', async () => {
  const text = await readFile(new URL('../src/lib/assistantControls.ts', import.meta.url), 'utf8');
  const code = ts.transpileModule(text.slice(text.indexOf('export function assistantFeatureChoices'), text.indexOf('export function useAssistantCanvasButton')).replace('export ', ''),
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const control = { type: 'select', label: 'Protein / Site', options: Array.from({ length: 80 }, (_, index) => `K${index}`) };
  const choices = new Function('controls', code + '\nreturn assistantFeatureChoices;')(new Map([['feature', { read: () => control }]]));
  assert.match(choices('feature', 'K'), /80 matches/);
  assert.match(choices('feature', 'K'), /first 5/);
  assert.equal(choices('feature', 'k79'), '');
  assert.equal(choices('feature', 'missing'), '');
  assert.equal(choices('absent', 'K'), '');
  control.options = ['AKT1', 'AKT2', 'AKT2'];
  assert.match(choices('feature', 'AKT'), /2 matches: "AKT1", "AKT2"/);
  control.label = 'Condition';
  assert.equal(choices('feature', 'AKT'), '');
  control.label = 'Tile 1: proteinBoxplot / Protein or gene';
  assert.match(choices('feature', 'AKT'), /2 matches/);
  control.type = 'multiple';
  assert.equal(choices('feature', 'AKT'), '');
});

test('typed canvas batches validate bounds and stop on wrong-type or partial additions', async () => {
  const text = await readFile(new URL('../src/lib/assistantControls.ts', import.meta.url), 'utf8');
  const code = ts.transpileModule(text.slice(text.indexOf('export function addCanvasTiles'), text.indexOf('\nfunction validate(')).replace('export ', ''),
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  let selected = '', wrong = false, failAt = Infinity;
  const tiles = new Map([['existing', 'volcano']]);
  const receipts = [];
  const controls = new Map([['type', { read: () => ({ id: 'type', label: 'New tile type', type: 'select', permission: 'view' }) }]]);
  const buttons = new Map([['add', { read: () => ({ id: 'add', label: '+ Add Plot', permission: 'view' }) }]]);
  const document = { querySelectorAll: () => [...tiles].map(([id, type]) => ({ getAttribute: name => name === 'data-assistant-tile' ? id : type })) };
  const add = new Function('controls', 'buttons', 'document', 'applyAssistantControls', 'activateAssistantButton', code + '\nreturn addCanvasTiles;')(
    controls, buttons, document, actions => { selected = actions[0].value; }, () => {
      if (tiles.size >= failAt) throw new Error('Unavailable');
      tiles.set(`new-${tiles.size}`, wrong ? 'oraList' : selected);
    });
  for (const value of [null, '{}', '{"type":"proteinBoxplot","count":9}', '{"type":"proteinBoxplot","count":1.5}', '{"type":"__proto__","count":1}']) {
    assert.throws(() => add(value, 8, receipt => receipts.push(receipt)));
  }
  assert.equal(tiles.size, 1);
  assert.match(add('{"type":"proteinBoxplot","count":2}', 8, receipt => receipts.push(receipt)), /Added 2 Protein Boxplot tiles/);
  assert.equal(receipts.length, 2);
  assert.equal(tiles.get('existing'), 'volcano');
  assert.throws(() => add('{"type":"volcano","count":2}', 1, () => {}));
  wrong = true;
  assert.throws(() => add('{"type":"volcano","count":1}', 8, () => assert.fail()), /confirm the requested plot type/);
  wrong = false;
  failAt = tiles.size + 1;
  const partial = [];
  assert.throws(() => add('{"type":"volcano","count":2}', 8, receipt => partial.push(receipt)), /Unavailable/);
  assert.equal(partial.length, 1);
});

async function scenario(replies, { decline = false, changeBeforeRequest = false, applied = [], buttonApproval = 'Remove this canvas tile?', activated = [], controls = [], choices = '', progress = () => {}, initialModule = 'qc.coverage', previousState = null } = {}) {
  const calls = [], remembered = [];
  let module = initialModule;
  const controller = new AbortController();
  const oldWindow = globalThis.window;
  let revision = 1;
  let advanced = false;
  globalThis.window = { setTimeout: callback => {
    if (changeBeforeRequest) revision = 2;
    queueMicrotask(callback); return 0;
  }, confirm: () => !decline };
  globalThis.assistantHarness = {
    flushSync: callback => callback(),
    focusCanvas: () => 'Focused the canvas.',
    assistantStep: async (payload) => {
      calls.push(structuredClone(payload));
      const reply = replies.shift();
      assert.ok(reply, 'Unexpected extra assistant request');
      if (reply.error) throw new Error(reply.error);
      if (reply.cancel) controller.abort();
      if (reply.mutate) reply.mutate();
      return { model: 'mock', revision: 1, answer: '', evidence: [], actions: [], ...reply };
    },
    hasPendingUiRequests: () => false,
    readAssistantControls: (_message, searches) => controls.map(control => ({ ...control,
      optionQuery: searches[control.id] || '',
      options: (control.options || []).filter(option => !searches[control.id] || option.includes(searches[control.id])),
    })), assistantSurfaceReady: () => true,
    searchAssistantOptions: (_target, value) => value,
    assistantFeatureChoices: () => choices,
    assistantButtonConfirmation: () => buttonApproval,
    activateAssistantButton: target => { activated.push(target); return 'Canvas button completed.'; },
    assistantConfirmation: () => ['Test: old → new'],
    applyAssistantControls: (actions, receipt) => actions.forEach(action => {
      applied.push(action);
      const control = controls.find(control => control.id === action.target);
      if (control) control.value = action.value;
      receipt('Changed test.');
    }),
    getAdvancedPlotMode: () => advanced, setAdvancedPlotMode: value => { advanced = value; },
    stableSnapshot: JSON.stringify,
    unsavedAnalysis: { capture: () => ({ revision, pending: false }) },
    AssistantConversation: class {},
  };
  const prelude = `const {${Object.keys(globalThis.assistantHarness).join(',')}} = globalThis.assistantHarness;\n`;
  const compiled = ts.transpileModule(prelude + source + `\n// scenario ${serial++}`, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  try {
    const { runAssistant } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
    const result = await runAssistant({ message: 'Open CV and explain it' },
      () => ({ module, workflow: 'protein', mode: { view: module }, destinations: { 'qc.cv': 'CV', 'analysis.canvas': 'Analysis' } }),
      target => { module = target; }, progress, controller.signal,
      { read: () => previousState, record: (...args) => remembered.push(args[4]), clear: () => {} });
    return { result, calls, remembered };
  } finally {
    globalThis.window = oldWindow;
    delete globalThis.assistantHarness;
  }
}

const navigate = () => ({ explainAfterChanges: true, actions: [{ type: 'navigate', target: 'qc.cv' }] });

test('volcano to canvas carries live comparison even after manual changes', async () => {
  const controls = [{id:'first', label:'Condition 1', type:'select', value:'Vehicle'},
                    {id:'second', label:'Condition 2', type:'select', value:'Treated'}];
  const {calls} = await scenario([{actions:[{type:'navigate', target:'analysis.canvas'}]}, {}], {
    initialModule:'stats.volcano', controls,
    previousState:{module:'stats.volcano', workflow:'protein', selections:[{label:'Condition 1',value:'Treated'}, {label:'Condition 2',value:'Vehicle'}]},
  });
  assert.deepEqual(calls[1].conversationState.selections, controls.map(({label,value})=>({label,value})));
  assert.equal(calls[1].conversationState.module, 'stats.volcano');
});

test('a repeated canvas addition requires approval and declining preserves the first tile', async () => {
  const activated = [];
  const add = { actions: [{ type: 'activate_control', target: 'add' }] };
  const { calls, result } = await scenario([
    { actions: [{ type: 'navigate', target: 'analysis.canvas' }] }, add, add,
  ], { decline: true, buttonApproval: '', activated });
  assert.deepEqual(activated, ['add']);
  assert.equal(calls.length, 3);
  assert.match(result.answer, /Another plot was declined/);
});

test('an explicitly approved repeated addition remains possible', async () => {
  const activated = [];
  const add = { actions: [{ type: 'activate_control', target: 'add' }] };
  await scenario([
    { actions: [{ type: 'navigate', target: 'analysis.canvas' }] }, add, add, {},
  ], { buttonApproval: '', activated });
  assert.deepEqual(activated, ['add', 'add']);
});

test('canvas identifier recovery is disclosed alongside the applied receipt', async () => {
  const { result, calls } = await scenario([
    { actions: [{ type: 'navigate', target: 'analysis.canvas' }] },
    { answer: "Resolved 'K0.' to uploaded identifier 'K0'.", actions: [{ type: 'focus_canvas', value: '{}' }] },
  ]);
  assert.equal(calls.length, 2);
  assert.match(result.answer, /Resolved 'K0\.'.*Focused the canvas/s);
});

test('advanced plot mode is the user\'s switch and the assistant cannot flip it', async () => {
  // Appearance settings register whether or not the panel is on screen, so the
  // assistant styles the plot directly; asking to open the panel is not an action.
  await assert.rejects(scenario([{ actions: [{ type: 'advanced_options', value: true }] }]), /unsupported action/);
});

test('option discovery does not claim that view settings changed', async () => {
  const { result } = await scenario([
    { actions: [{ type: 'search_options', target: 'protein', value: 'P1' }] },
    { answer: 'Which matching protein should I select?', needsClarification: true },
  ]);
  assert.doesNotMatch(result.answer, /Updated the requested view|Searched selection/);
  assert.equal(result.evidence[0].tool, 'Assistant steps');
});

test('mixed request explains the settled new view after finishing changes', async () => {
  const { result, calls } = await scenario([navigate(), {}, { answer: 'Observed CV.', evidence: [{ tool: 'CV', status: 'available', text: 'Fresh results' }] }]);
  assert.deepEqual(calls.map(call => call.answerOnly), [false, false, true]);
  assert.equal(calls[2].view.module, 'qc.cv');
  assert.deepEqual(calls[2].view.mode, { view: 'qc.cv' });
  assert.deepEqual(calls[2].receipts, ['Opened CV.']);
  assert.match(result.answer, /Opened CV.*Observed CV/s);
});

test('canvas focus hands a pending explanation the final view and verified receipt', async () => {
  const { result, calls } = await scenario([
    { explainAfterChanges: true, actions: [{ type: 'navigate', target: 'analysis.canvas' }] },
    { actions: [{ type: 'focus_canvas', value: '{}' }] },
    { answer: 'Canvas evidence.', evidence: [{ tool: 'canvas', status: 'available', text: 'Fresh result' }] },
  ]);
  assert.deepEqual(calls.map(call => call.answerOnly), [false, false, true]);
  assert.equal(calls[2].view.module, 'analysis.canvas');
  assert.deepEqual(calls[2].receipts, ['Opened Analysis.', 'Focused the canvas.']);
  assert.match(result.answer, /Focused the canvas.*Canvas evidence/s);
});

test('the final planning slot can hand off to one read-only explanation', async () => {
  const changes = Array.from({ length: 7 }, (_, i) => ({ explainAfterChanges: true,
    actions: [{ type: 'set_control', target: `control${i}`, value: 'new' }] }));
  const { result, calls } = await scenario([...changes, {}, { answer: 'Final evidence.', evidence: [{ tool: 'test', status: 'available', text: 'Result' }] }]);
  assert.equal(calls.length, 9);
  assert.equal(calls[8].answerOnly, true);
  assert.equal(calls[8].receipts.length, 7);
  assert.match(result.answer, /Final evidence/);
});

test('declining changes does not start an explanation', async () => {
  const { calls, remembered, result } = await scenario([
    { explainAfterChanges: true, actions: [{ type: 'set_control', target: 'test', value: 'new' }] },
  ], { decline: true });
  assert.equal(calls.length, 1);
  assert.deepEqual(remembered, ['declined']);
  assert.match(result.answer, /declined/);
});

test('explanation phase rejects unexpected actions even from the server', async () => {
  await assert.rejects(scenario([navigate(), {}, { actions: [{ type: 'navigate', target: 'analysis.canvas' }] }]), /cannot apply further/);
});

test('clarification stops rather than silently starting an explanation', async () => {
  const { calls, remembered } = await scenario([navigate(), { needsClarification: true, answer: 'Which condition?' }]);
  assert.equal(calls.length, 2);
  assert.deepEqual(remembered, ['needs_clarification']);
});

test('a conflicting clarification response cannot apply controls', async () => {
  const applied = [];
  await assert.rejects(scenario([{ needsClarification: true, answer: 'Which labels?',
    actions: [{ type: 'set_control', target: 'labels', value: '45' }] }], { applied }),
  /clarification and changes together/);
  assert.deepEqual(applied, []);
});

test('cancellation after an action does not start an explanation', async () => {
  await assert.rejects(scenario([navigate(), { cancel: true }]), { name: 'AbortError' });
});

test('ordinary UI requests do not add an explanation call', async () => {
  const { calls } = await scenario([{ actions: [{ type: 'navigate', target: 'qc.cv' }] }, {}]);
  assert.equal(calls.length, 2);
});

test('repeated navigation stops without replaying or claiming full completion', async () => {
  const { result, calls, remembered } = await scenario([navigate(), navigate()]);
  assert.equal(calls.length, 2);
  assert.deepEqual(remembered, ['needs_clarification']);
  assert.deepEqual(result.actions, []);
  assert.match(result.answer, /Opened CV.*stopped a repeated step.*explanation is still pending/s);
});

test('repeated search stops on the second request without claiming a selection', async () => {
  const search = { actions: [{ type: 'search_options', target: 'protein', value: 'P1' }] };
  const { result, calls, remembered } = await scenario([search, search]);
  assert.equal(calls.length, 2);
  assert.deepEqual(remembered, ['needs_clarification']);
  assert.match(result.answer, /choose an exact identifier or narrow/);
  assert.doesNotMatch(result.answer, /Updated|Set |Searched selection/);
});

test('alternating searches cannot evade the no-progress guard', async () => {
  const search = value => ({ actions: [{ type: 'search_options', target: 'protein', value }] });
  const { result, calls } = await scenario([search('P1'), search('P2'), search('P1')], {
    controls: [{ id: 'protein', value: '', options: ['P1', 'P2'], optionCount: 2 }],
  });
  assert.equal(calls.length, 3);
  assert.equal(result.needsClarification, true);
});

test('a changed selection permits a fresh search with the same query', async () => {
  const search = { actions: [{ type: 'search_options', target: 'protein', value: 'P1' }] };
  const { result, calls } = await scenario([search,
    { actions: [{ type: 'set_control', target: 'condition', value: 'B' }] }, search, {}], {
    controls: [{ id: 'protein', value: '', options: ['P1'], optionCount: 1 }, { id: 'condition', value: 'A' }],
  });
  assert.equal(calls.length, 4);
  assert.ok(!result.needsClarification);
});

test('repeated identical setters do not apply twice', async () => {
  const applied = [];
  const set = { actions: [{ type: 'set_control', target: 'test', value: 'new' }] };
  const { result } = await scenario([set, set], { applied, controls: [{ id: 'test', value: 'old' }] });
  assert.equal(applied.length, 1);
  assert.equal(result.needsClarification, true);
});

test('a different next action still runs after an earlier completed action', async () => {
  const applied = [];
  const { result } = await scenario([navigate(), { actions: [{ type: 'set_control', target: 'test', value: 'new' }] },
    {}, { answer: 'Fresh explanation.', evidence: [{ tool: 'test', status: 'available', text: 'Fresh result' }] }], { applied });
  assert.equal(applied.length, 1);
  assert.match(result.answer, /Fresh explanation/);
  assert.ok(!result.needsClarification);
});

test('fallback records incomplete without losing completed changes or retrying', async () => {
  const { result, remembered, calls } = await scenario([navigate(), {}, {
    usedEvidenceFallback: true, answer: 'Evidence fallback.', evidence: [],
  }]);
  assert.deepEqual(remembered, ['incomplete']);
  assert.equal(calls.length, 3);
  assert.match(result.answer, /Opened CV.*Evidence fallback/s);
  assert.equal(result.evidence.at(-1).text, 'Opened CV.');
});

test('dataset changes while waiting prevent even the next assistant request', async () => {
  await assert.rejects(scenario([], { changeBeforeRequest: true }), /analysis changed/);
});

test('a batch cannot exceed the remaining total action budget', async () => {
  const applied = [];
  const batch = size => ({ actions: Array.from({ length: size }, (_, i) => ({ type: 'set_control', target: `control${i}`, value: 'new' })) });
  await assert.rejects(scenario([batch(4), batch(3), batch(2)], { applied }), /exceed the remaining.*No changes from this batch/);
  assert.equal(applied.length, 7);
});


test('an explanation re-asks once a view that moved during the request has settled', async () => {
  const controls = [{ id: 'tile', label: 'Tile 1: volcano / Condition 1', value: 'loading' }];
  const settle = () => { controls[0].value = 'loaded'; };
  const { result, calls } = await scenario([navigate(), {},
    { mutate: settle, answer: 'Explained the half-loaded view.', evidence: [{ tool: 't', status: 'available', text: 'x' }] },
    { answer: 'Explained the loaded view.', evidence: [{ tool: 't', status: 'available', text: 'x' }] }], { controls });
  assert.equal(calls.length, 4);
  assert.deepEqual(calls.map(call => call.answerOnly), [false, false, true, true]);
  assert.match(result.answer, /loaded view/);
  assert.doesNotMatch(result.answer, /half-loaded/);
});

test('a view that never settles still ends with the change error', async () => {
  const controls = [{ id: 'tile', label: 'Tile', value: 0 }];
  const churn = { mutate: () => { controls[0].value += 1; }, answer: 'Stale.', evidence: [{ tool: 't', status: 'available', text: 'x' }] };
  await assert.rejects(scenario([navigate(), {}, churn, churn, churn, churn], { controls }), /view or analysis changed/);
});

test('late explanation retries do not consume the last planning slot', async () => {
  const controls = [{ id: 'width', label: 'Width', value: 0 }];
  const changes = Array.from({ length: 6 }, (_, index) => ({
    actions: [{ type: 'set_control', target: 'width', value: index + 1 }],
  }));
  const evidence = [{ tool: 't', status: 'available', text: 'x' }];
  const { result, calls } = await scenario([navigate(), ...changes, {},
    { mutate: () => { controls[0].value = 7; }, answer: 'Stale answer.', evidence },
    { answer: 'Settled answer.', evidence },
  ], { controls });
  assert.equal(calls.length, 10);
  assert.match(result.answer, /Settled answer/);
  assert.doesNotMatch(result.answer, /Stale answer/);
});

test('a setter repeated on remounted controls is still recognised as a repeat', async () => {
  const applied = [];
  // React gives a remounted control a new id; its label and value are unchanged.
  const controls = [{ get id() { return applied.length ? 'width [r2]' : 'width [r1]'; }, label: 'Width',
    get value() { return applied.length ? 'new' : 'old'; } }];
  const { result, calls } = await scenario([
    { actions: [{ type: 'set_control', target: 'width [r1]', value: 'new' }] },
    { actions: [{ type: 'set_control', target: 'width [r2]', value: 'new' }] },
  ], { applied, controls });
  assert.equal(calls.length, 2);
  assert.equal(applied.length, 1);
  assert.equal(result.needsClarification, true);
});

test('a prefix request lists every prefix match even when one matches exactly', async () => {
  const text = await readFile(new URL('../src/lib/assistantControls.ts', import.meta.url), 'utf8');
  const code = ts.transpileModule(text.slice(text.indexOf('export function assistantFeatureChoices'), text.indexOf('export function useAssistantCanvasButton')).replace('export ', ''),
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const control = { type: 'select', label: 'Protein / Site', options: ['K7', 'K17', ...Array.from({ length: 10 }, (_, i) => `K7${i}`)] };
  const choices = new Function('controls', code + '\nreturn assistantFeatureChoices;')(new Map([['feature', { read: () => control }]]));
  assert.equal(choices('feature', 'K7'), '', 'without prefix intent an exact match is selectable');
  const listed = choices('feature', 'K7', 'Find the site whose identifier starts with K7');
  assert.match(listed, /11 matches: "K7", "K70"/);
  assert.doesNotMatch(listed, /K17/);
});

// ---- section 38 (iteration 21 follow-up) ----------------------------------

test('a scope note next to applied setters reaches the answer and the next planning step', async () => {
  const controls = [{ id: 'rot', label: 'X axis / X tick label rotation', type: 'number', value: '0', permission: 'view', options: [] }];
  const note = 'The request is about a sample, but Condition names / A changes a condition. No sample-level control for that is available in this view, so I left it unchanged.';
  const { result, calls } = await scenario([
    { actions: [{ type: 'set_control', target: 'rot', value: '45' }], answer: note },
    {},
  ], { controls });
  assert.deepEqual(calls[1].notes, [note]);
  assert.match(result.answer, /Changed test\./);
  assert.match(result.answer, /left it unchanged/);
  assert.doesNotMatch(result.answer, /No supported action/);
});

test('a note survives the hand-off to the explanation step', async () => {
  const controls = [{ id: 'rot', label: 'X axis / X tick label rotation', type: 'number', value: '0', permission: 'view', options: [] }];
  const { result, calls } = await scenario([
    { explainAfterChanges: true, actions: [{ type: 'set_control', target: 'rot', value: '45' }] },
    { answer: 'The request does not name condition B, so I left Condition colors / B unchanged.' },
    { answer: 'Explanation of the rotated plot.' },
  ], { controls });
  assert.equal(calls[2].answerOnly, true);
  assert.match(result.answer, /left Condition colors \/ B unchanged/);
  assert.match(result.answer, /Explanation of the rotated plot/);
});

test('a stop survives a full note buffer and the explanation response', async () => {
  const controls = [{ id: 'rot', label: 'Rotation', type: 'number', value: '0', permission: 'view', options: [] }];
  const changes = Array.from({ length: 4 }, (_, i) => ({
    explainAfterChanges: true, actions: [{ type: 'set_control', target: 'rot', value: String(i + 1) }],
    answer: `Scope note ${i + 1}.`,
  }));
  const { result, remembered } = await scenario([...changes,
    { stoppedEarly: true, explainAfterChanges: true, answer: 'Stopped with requested work still incomplete.' },
    { answer: 'Explanation of the current plot.' },
  ], { controls });
  assert.equal(result.stoppedEarly, true);
  assert.match(result.answer, /Scope note 4/);
  assert.match(result.answer, /work still incomplete/);
  assert.match(result.answer, /Explanation of the current plot/);
  assert.deepEqual(remembered, ['incomplete']);
});

test('scope notes and completed changes remain visible after a later provider error', async () => {
  const updates = [];
  const controls = [{ id: 'rot', label: 'Rotation', type: 'number', value: '0', permission: 'view', options: [] }];
  await assert.rejects(scenario([
    { actions: [{ type: 'set_control', target: 'rot', value: '45' }], answer: 'Sample rename was left unchanged.' },
    { error: 'Invalid subsequent plan' },
  ], { controls, progress: text => updates.push(text) }), /Invalid subsequent plan/);
  assert.match(updates.at(-1), /Changed test/);
  assert.match(updates.at(-1), /Sample rename was left unchanged/);
});

test('control labels carry every enclosing group so the X and Y axis labels differ', async () => {
  const text = await readFile(new URL('../src/lib/assistantControls.ts', import.meta.url), 'utf8');
  const code = ts.transpileModule(text.slice(text.indexOf('function groupPath'), text.indexOf('function description')),
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const groupPath = new Function(code + '\nreturn groupPath;')();
  const node = (name, parent) => ({
    getAttribute: () => name, parentElement: parent ? { closest: () => parent } : null,
    closest: function () { return this; },
  });
  const section = node('X axis', null);
  const card = node('Axis label', section);
  const input = { closest: () => card };
  assert.equal(groupPath(input), 'X axis / Axis label');
  const title = node('Title', null);
  assert.equal(groupPath({ closest: () => node('Title', title) }), 'Title');
  assert.equal(groupPath({ closest: () => null }), '');
});

// ---- section 40 (iteration 22 follow-up) ----------------------------------

test('a rejected later proposal ends with the completed changes and an incomplete status', async () => {
  const controls = [{ id: 'rot', label: 'X axis / X tick label rotation', type: 'number', value: '0', permission: 'view', options: [] }];
  const stop = 'I made the changes above and stopped there: Invalid value for Dataset level. Nothing else was changed, so ask again for anything still missing.';
  const { result, remembered } = await scenario([
    { actions: [{ type: 'set_control', target: 'rot', value: '45' }] },
    { stoppedEarly: true, answer: stop },
  ], { controls });
  assert.match(result.answer, /Changed test\./);
  assert.match(result.answer, /I made the changes above and stopped there/);
  assert.deepEqual(remembered, ['incomplete']);
});

test('an explanation still follows a clean stop when one was requested', async () => {
  const controls = [{ id: 'rot', label: 'X axis / X tick label rotation', type: 'number', value: '0', permission: 'view', options: [] }];
  const { result, calls } = await scenario([
    { explainAfterChanges: true, actions: [{ type: 'set_control', target: 'rot', value: '45' }] },
    { stoppedEarly: true, explainAfterChanges: true, answer: 'I made the changes above and stopped there.' },
    { answer: 'Explanation of the rotated plot.' },
  ], { controls });
  assert.equal(calls[2].answerOnly, true);
  assert.match(result.answer, /I made the changes above and stopped there/);
  assert.match(result.answer, /Explanation of the rotated plot/);
});
