import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/lib/assistantConversation.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
const { AssistantConversation } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const view = { module: 'singleProtein.boxplot', workflow: 'protein', mode: {}, destinations: {}, controls: [
  { label: 'Protein / Site', value: 'P53' }, { label: 'Condition 1', value: 'A' },
  { label: 'API key', value: 'do-not-retain' }, { label: 'Invented result', value: 'do-not-retain' },
] };

test('conversation retains only observed selection fields and explicit task state', () => {
  const memory = new AssistantConversation();
  memory.record(2, 'Show this protein', view, ['Opened boxplot.'], 'interrupted');
  assert.deepEqual(memory.read(2).selections, [{ label: 'Protein / Site', value: 'P53' }, { label: 'Condition 1', value: 'A' }]);
  assert.equal(memory.read(2).status, 'interrupted');
  assert.equal(JSON.stringify(memory.read(2)).includes('do-not-retain'), false);
});

test('data revision change and explicit reset invalidate conversational selections', () => {
  const memory = new AssistantConversation();
  memory.record(2, 'Show this protein', view, [], 'completed');
  assert.equal(memory.read(3), null);
  memory.record(3, 'Show this protein', view, [], 'completed');
  memory.clear();
  assert.equal(memory.read(3), null);
});

test('conversation size is bounded', () => {
  const memory = new AssistantConversation();
  memory.record(1, 'q'.repeat(10000), { ...view, controls: [{ label: 'Protein', value: 'x'.repeat(10000) }] }, ['r'.repeat(10000)], 'declined');
  assert.equal(memory.read(1).request.length, 1000);
  assert.equal(memory.read(1).completed[0].length, 200);
  assert.deepEqual(memory.read(1).selections, []);
});

test('incomplete answers retain observed UI receipts, not generated conclusions', () => {
  const memory = new AssistantConversation();
  memory.record(1, 'Open the plot and explain it', view, ['Opened boxplot.'], 'incomplete');
  assert.equal(memory.read(1).status, 'incomplete');
  assert.deepEqual(memory.read(1).completed, ['Opened boxplot.']);
  assert.equal(memory.read(2), null);
});
