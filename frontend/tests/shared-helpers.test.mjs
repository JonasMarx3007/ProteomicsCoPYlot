import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

test('duplicate control targets are rejected before any browser change or confirmation', async () => {
  const source = await readFile(new URL('../src/lib/assistantControls.ts', import.meta.url), 'utf8');
  const excerpt = source.slice(source.indexOf('export function applyAssistantControls'));
  const compiled = ts.transpileModule(excerpt, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText.replaceAll('export ', '');
  const apply = new Function('assistantConfirmation', compiled + '\nreturn applyAssistantControls;')(
    () => assert.fail('Duplicate batch reached confirmation'));
  assert.throws(() => apply([
    { type: 'set_control', target: 'width', value: '10' },
    { type: 'set_control', target: 'width', value: '20' },
  ]), /only once per batch/);
});

async function loadModule(path) {
  const source = await readFile(new URL(`../src/lib/${path}.ts`, import.meta.url), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022,
  } }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
}

const { collectColumns, rowsToCsv, rowsToQuotedCsv, formatCellValue } = await loadModule('tableData');
const { compactMap, compactTextElement } = await loadModule('plotSerialization');
const { resolveSelectedLocalPath } = await loadModule('localFilePath');

test('ORA restoration separates editable inputs from completed results and rejects broken snapshots', async () => {
  const source = await readFile(new URL('../src/features/analysis/AnalysisPage.tsx', import.meta.url), 'utf8');
  const helpers = source.slice(source.indexOf('function asString('), source.indexOf('function asStringArray(')) +
    source.slice(source.indexOf('function restoredOraState('), source.indexOf('function uid('));
  const compiled = ts.transpileModule(helpers, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const restore = new Function(compiled + '\nreturn restoredOraState;')();
  const completed = {
    inputSource: 'list', namedList: 'original',
    request: { genes: ['G1'], backgroundGenes: [], backgroundMode: 'global', topN: 10, minTermSize: 20, maxTermSize: 300, adjPValueCutoff: .05 },
    result: { genes: ['G1'], backgroundGenes: [], backgroundMode: 'global', warnings: [], organism: 'human', correctionMethod: 'BH', databaseSha256: 'synthetic',
      backgroundSize: 100, annotatedBackgroundSize: 100, testedTermCount: 1, evidenceToken: 'saved-token',
      termCounts: { query: { searchSpace: 1, overlapTested: 1, passingCutoff: 1, displayed: 1 } },
      terms: [{ source: 'GO', termId: 'T', name: 'term', termSize: 20, intersectionSize: 1, hitPercent: 5, pValue: .01, adjPValue: .01, intersectingGenes: ['G1'] }] },
  };
  const restored = restore({ sourceMode: 'manual', genesText: 'G2', adjPValueCutoff: .5, completed });
  assert.equal(restored.genesText, 'G2');
  assert.equal(restored.adjPValueCutoff, .5);
  assert.deepEqual(restored.completed, completed);
  assert.equal(restore(null).completed, null);
  assert.equal(restore({ genesText: 'G2', completed: {} }).genesText, 'G2');
  for (const damage of [
    value => { value.result.terms[0].adjPValue = 'invalid'; },
    value => { value.result.termCounts = null; },
    value => { value.result.warnings = {}; },
    value => { value.request = null; },
  ]) {
    const malformed = structuredClone(completed);
    damage(malformed);
    assert.equal(restore({ completed: malformed }).completed, null);
  }
  const empty = structuredClone(completed);
  empty.result.terms = [];
  assert.deepEqual(restore({ completed: empty }).completed, empty);
});

test('targeted option search handles exact matches, empty results and read-only discovery', async () => {
  const source = await readFile(new URL('../src/lib/assistantControls.ts', import.meta.url), 'utf8');
  const excerpt = source.slice(source.indexOf('export function readAssistantControls'), source.indexOf('export function useAssistantCanvasButton'));
  const compiled = ts.transpileModule(excerpt, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText.replaceAll('export ', '');
  const control = { id: 'protein', label: 'Protein', type: 'select', value: 'P1', options: Array.from({ length: 100 }, (_, i) => `P${i}`), optionCount: 100, permission: 'view' };
  const { readAssistantControls, searchAssistantOptions } = new Function('controls', 'buttons', compiled + '\nreturn { readAssistantControls, searchAssistantOptions };')(
    new Map([['protein', { read: () => structuredClone(control) }]]), new Map());
  assert.equal(readAssistantControls()[0].options.length, 40);
  assert.equal(searchAssistantOptions('protein', ' P99 '), 'P99');
  assert.deepEqual(readAssistantControls('', { protein: 'P99' })[0].options, ['P99']);
  const missing = readAssistantControls('', { protein: 'absent' })[0];
  assert.equal(missing.optionMatchCount, 0);
  assert.deepEqual(missing.options, []);
  assert.equal(missing.value, 'P1');
  assert.throws(() => searchAssistantOptions('missing', 'P1'));
  assert.throws(() => searchAssistantOptions('protein', ''));
});

test('assistant passes cancellation through to fetch', async () => {
  const source = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
  const start = source.indexOf('export async function assistantStep(');
  const end = source.indexOf('\n}', start) + 2;
  const compiled = ts.transpileModule('const API_BASE = "";\n' + source.slice(start, end), {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const { assistantStep } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
  const previous = globalThis.fetch;
  const controller = new AbortController();
  globalThis.fetch = async (_url, options) => {
    assert.equal(options.signal, controller.signal);
    throw new DOMException('Stopped', 'AbortError');
  };
  try {
    await assert.rejects(assistantStep({ message: 'hello', view: {}, receipts: [] }, controller.signal), { name: 'AbortError' });
  } finally { globalThis.fetch = previous; }
});

test('selection context preserves delimiters, arrays and Unicode', async () => {
  const { contextMode } = await loadModule('plotSerialization');
  const names = ['P1;P2', 'Drug, high', 'A|B=δ', '100% ready', 'quote"name'];
  const mode = contextMode([`protein=${names[2]}`, `proteins=${JSON.stringify(names)}`,
    `conditions=${JSON.stringify(names)}`, 'header=false']);
  assert.deepEqual(JSON.parse(mode), { protein: names[2], proteins: names, conditions: names, header: 'false' });
  const query = new URLSearchParams({ proteins: JSON.stringify(names) });
  assert.deepEqual(JSON.parse(new URLSearchParams(query.toString()).get('proteins')), names);
});

test('report context retains peptide coverage alongside module settings and missingness choices', async () => {
  const previous = globalThis.sessionStorage;
  const entries = new Map();
  globalThis.sessionStorage = {
    getItem: key => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
  };
  try {
    const persisted = await readFile(new URL('../src/lib/persistedUiState.ts', import.meta.url), 'utf8');
    const source = await readFile(new URL('../src/lib/reportState.ts', import.meta.url), 'utf8');
    const compile = text => ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
    const url = text => `data:text/javascript;base64,${Buffer.from(text).toString('base64')}`;
    const compiled = compile(source)
      .replace('"./persistedUiState"', JSON.stringify(url(compile(persisted))))
      .replace('"./appSettings"', JSON.stringify(url('export const getAdvancedPlotMode=()=>false; export const getAdvancedPlotSettingsByKey=()=>({});')));
    const report = await import(url(compiled));
    report.saveQcReportSettings('peptide', { coverage: { quantityColumn: 'LFQ intensity' } });
    report.saveQcReportSettings('peptide', { rtPlot: { method: 'Scatter' } });
    const missingPlot = { quantityColumn: 'LFQ intensity', binCount: 2, header: false, widthCm: 25 };
    entries.set('pcopylot.ui.completeness.v1', JSON.stringify({ missingPlot }));
    const context = report.getSummaryReportContext();
    assert.deepEqual(context.qcSettings.peptide, { coverage: { quantityColumn: 'LFQ intensity' }, rtPlot: { method: 'Scatter' } });
    assert.deepEqual(context.completenessSettings, missingPlot);
  } finally {
    globalThis.sessionStorage = previous;
  }
});

test('control comparisons expose only distinct methods and restore legacy unpaired settings', async () => {
  const { CONTROL_TEST_TYPE_OPTIONS, controlTestType, TEST_TYPE_OPTIONS } = await loadModule('statisticalTests');
  assert.deepEqual(CONTROL_TEST_TYPE_OPTIONS.map(({ value }) => value), ['unpaired_welch', 'paired']);
  assert.equal(controlTestType('unpaired'), 'unpaired_welch');
  assert.equal(controlTestType('unpaired_welch'), 'unpaired_welch');
  assert.equal(controlTestType('paired'), 'paired');
  assert.equal(TEST_TYPE_OPTIONS.length, 3);
});

test('CSV serializers escape headers and retain every row without rounding', () => {
  const columns = ['sample,1', 'say "hi"', 'line\nbreak', 'carriage\rreturn', 'number'];
  const rows = Array.from({ length: 205 }, (_, i) => ({
    'sample,1': `P${i}`, 'say "hi"': 'a"b', 'line\nbreak': 'x\ny',
    'carriage\rreturn': 'x\ry', number: 0.12345678901234568,
  }));
  const header = '"sample,1","say ""hi""","line\nbreak","carriage\rreturn"';
  assert.equal(rowsToCsv(rows, columns), header + ',number\n' + rows.map((_, i) =>
    `P${i},"a""b","x\ny","x\ry",0.12345678901234568`).join('\n'));
  assert.equal(rowsToQuotedCsv(rows, columns), header + ',"number"\n' + rows.map((_, i) =>
    `"P${i}","a""b","x\ny","x\ry","0.12345678901234568"`).join('\n'));
});

test('analysis snapshots stay tab-local and exclude the tab routing ID', async () => {
  const restore = await loadModule('restoreUiState');
  const previous = globalThis.sessionStorage;
  const entries = new Map([
    ['copylot.tab.id', 'a'.repeat(32)],
    ['pcopylot.report.qcSettings.v1', '{"title":"Only this tab"}'],
    ['unrelated', 'keep'],
  ]);
  globalThis.sessionStorage = {
    get length() { return entries.size; },
    key: index => [...entries.keys()][index],
    getItem: key => entries.get(key) ?? null,
    setItem: (key, value) => entries.set(key, value),
    removeItem: key => entries.delete(key),
  };
  try {
    assert.deepEqual(restore.captureCopylotSessionStorageState(), {
      'pcopylot.report.qcSettings.v1': '{"title":"Only this tab"}',
    });
    restore.applyCopylotSessionStorageState({ 'copylot.tab.id': 'foreign', 'pcopylot.ui.plot': 'restored' });
    assert.equal(entries.get('copylot.tab.id'), 'a'.repeat(32));
    assert.equal(entries.get('pcopylot.ui.plot'), 'restored');
    restore.clearCopylotClientStorageState();
    assert.deepEqual([...entries], [['copylot.tab.id', 'a'.repeat(32)], ['unrelated', 'keep']]);
  } finally {
    if (previous === undefined) delete globalThis.sessionStorage;
    else globalThis.sessionStorage = previous;
  }
});

test('canvas volcano styling validates saved colors and bounds point size', async () => {
  const source = await readFile(new URL('../src/features/analysis/AnalysisPage.tsx', import.meta.url), 'utf8');
  const helper = source.slice(source.indexOf('function restoredVolcanoStyle('), source.indexOf('type AnalysisTile ='));
  const compiled = ts.transpileModule(helper, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const restore = new Function(`${compiled}; return restoredVolcanoStyle;`)();
  const defaults = restore(null);
  assert.equal(defaults.radius, 2.8);
  assert.equal(restore({ radius: Infinity }).radius, 2.8);
  assert.equal(restore({ radius: -5 }).radius, 1);
  assert.equal(restore({ radius: 100 }).radius, 10);
  assert.equal(restore({ up: 'url(https://example.invalid/image)' }).up, defaults.up);
  assert.equal(restore({ up: '#abcdef' }).up, '#abcdef');
  assert.equal(restore({ title: { bad: true } }).title, '');
  assert.equal(restore({ title: 'A & B <test>' }).title, 'A & B <test>');
});

test('columns retain first-seen order across heterogeneous rows without mutation', () => {
  const rows = Object.freeze([Object.freeze({ b: 1, a: 2 }), Object.freeze({ c: 3, b: 4 })]);
  assert.deepEqual(collectColumns(rows), ['b', 'a', 'c']);
  assert.deepEqual(collectColumns([]), []);
});

test('preview formatting retains its existing rounding and nonnumeric representation', () => {
  assert.deepEqual([null, undefined, 0, 1.234567, true, false, { a: 1 }, 'text'].map(formatCellValue),
    ['', '', '0', '1.2346', 'true', 'false', '{"a":1}', 'text']);
});

test('CSV variants preserve precision, missing cells, escaping and existing empty behavior', () => {
  const rows = [{ n: 0.12345678901234568, text: 'a,"b"\nc', empty: null }];
  const columns = ['n', 'text', 'empty', 'missing'];
  assert.equal(rowsToCsv(rows, columns), 'n,text,empty,missing\n0.12345678901234568,"a,""b""\nc",,');
  assert.equal(rowsToQuotedCsv(rows, columns), '"n","text","empty","missing"\n"0.12345678901234568","a,""b""\nc","",""');
  assert.equal(rowsToCsv([], ['n']), 'n');
  assert.equal(rowsToQuotedCsv([], ['n']), '');
  assert.equal(rowsToQuotedCsv(rows, []), '');
});

test('plot text compaction retains signed offsets and explicit styling without mutation', () => {
  const value = Object.freeze({ text: ' Title ', size: 12, xOffset: -2, yOffset: 3, bold: true, italic: true });
  assert.deepEqual(compactTextElement(value), { text: 'Title', size: 12, xOffset: -2, yOffset: 3, bold: true, italic: true });
  assert.equal(compactTextElement(undefined), undefined);
  assert.equal(compactTextElement({ text: ' ', size: 0, xOffset: 0, yOffset: 0, bold: false }), undefined);
});

test('plot maps trim, omit blank entries and preserve the existing last-key-wins rule', () => {
  assert.deepEqual(compactMap({ ' a ': ' first ', a: 'last', b: ' ', ' ': 'x' }), { a: 'last' });
  assert.equal(compactMap(undefined), undefined);
});

test('upload and restore share native-path precedence and reject browser fake paths', () => {
  assert.equal(resolveSelectedLocalPath({ path: ' C:/data/a.tsv ' }, 'C:/other.tsv'), 'C:/data/a.tsv');
  assert.equal(resolveSelectedLocalPath({}, ' C:/data/a.tsv '), 'C:/data/a.tsv');
  assert.equal(resolveSelectedLocalPath({}, 'C:\\FAKEPATH\\a.tsv'), null);
  assert.equal(resolveSelectedLocalPath({ path: ' ' }, ''), null);
});
