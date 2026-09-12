import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

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

test('chat stream passes cancellation through to fetch and stops receiving chunks', async () => {
  const source = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
  const start = source.indexOf('export async function streamChatMessage(');
  const end = source.indexOf('\nfunction normalizeCloudAiConsentStatus', start);
  const compiled = ts.transpileModule('const API_BASE = "";\n' + source.slice(start, end), {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const { streamChatMessage } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
  const previous = globalThis.fetch;
  const controller = new AbortController();
  globalThis.fetch = async (_url, options) => {
    assert.equal(options.signal, controller.signal);
    return {
      ok: true, headers: new Headers(),
      body: { getReader: () => ({ read: () => new Promise((resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(new DOMException('Stopped', 'AbortError')), { once: true });
        queueMicrotask(() => controller.abort());
      }) }) },
    };
  };
  try {
    const chunks = [];
    await assert.rejects(streamChatMessage({ message: 'hello', messages: [] }, chunk => chunks.push(chunk), controller.signal), { name: 'AbortError' });
    assert.deepEqual(chunks, []);
  } finally {
    globalThis.fetch = previous;
  }
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
