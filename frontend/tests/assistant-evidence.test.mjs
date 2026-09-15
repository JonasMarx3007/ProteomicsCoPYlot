import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';

const source = await readFile(new URL('../src/components/AssistantEvidence.tsx', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  jsx: ts.JsxEmit.React, module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022,
} }).outputText.replace('export default ', '');
const Evidence = new Function('React', compiled + '\nreturn AssistantEvidence;')(React);

test('evidence presentation preserves numerical spelling, limitations and escaped content', () => {
  const text = 'result_row|adjPValue=4.01e-09|mean=0|label=<img src=x onerror=alert(1)>\nMissing counts remain unknown.';
  const html = renderToStaticMarkup(React.createElement(Evidence, { evidence: [{ tool: 'canvas_tile', status: 'partial', text }] }));
  assert.match(html, /Partial evidence/);
  assert.match(html, /<dl/);
  assert.match(html, /4.01e-09/);
  assert.match(html, /mean: /);
  assert.match(html, /Missing counts remain unknown/);
  assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /Source details/);
});

test('evidence display makes its own preview limit explicit without removing source records', () => {
  const text = Array.from({ length: 10 }, (_, i) => `row|value=${i}`).join('\n');
  const html = renderToStaticMarkup(React.createElement(Evidence, { evidence: [{ tool: 'test', status: 'available', text }] }));
  assert.equal((html.match(/<dl/g) ?? []).length, 8);
  assert.match(html, /Showing the first eight/);
  assert.match(html, /row\|value=9/);
});
