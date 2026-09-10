import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const source = await readFile(new URL('../src/components/OraTermCounts.tsx', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
} }).outputText.replace('"react/jsx-runtime"', JSON.stringify(import.meta.resolve('react/jsx-runtime')));
const { default: Counts } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('counts remain visible and downloadable when the result table is empty', () => {
  const html = renderToStaticMarkup(createElement(Counts, { counts: {
    query: { searchSpace: 40, overlapTested: 7, passingCutoff: 0, displayed: 0 },
  } }));
  assert.match(html, /Overlapping\/tested \(BH family\): 7/);
  assert.match(html, /Displayed terms: 0/);
  assert.match(html, /Zero-overlap terms are excluded/);
  const csv = decodeURIComponent(html.match(/href="data:text\/csv;charset=utf-8,([^"]+)"/)[1]);
  assert.match(csv, /query,40,7,0,0,/);
  assert.match(csv, /top-N display limit are applied afterward/);
});

test('directions have separate correction families rather than a misleading summed count', () => {
  const html = renderToStaticMarkup(createElement(Counts, { counts: {
    up: { searchSpace: 40, overlapTested: 7, passingCutoff: 3, displayed: 2 },
    down: { searchSpace: 40, overlapTested: 12, passingCutoff: 4, displayed: 2 },
  } }));
  assert.match(html, /Upregulated/);
  assert.match(html, /Downregulated/);
  assert.match(html, /BH family\): 7/);
  assert.match(html, /BH family\): 12/);
});
