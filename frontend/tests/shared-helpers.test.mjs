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
  assert.equal(rowsToQuotedCsv(rows, columns), 'n,text,empty,missing\n"0.12345678901234568","a,""b""\nc","",""');
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
