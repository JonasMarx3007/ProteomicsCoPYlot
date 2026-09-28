import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

// api.ts imports the app; only the helper is compiled here.
async function loadApiErrorMessage() {
  const source = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
  const start = source.indexOf('export function apiErrorMessage');
  const end = source.indexOf('\n}\n', start) + 3;
  const compiled = ts.transpileModule(source.slice(start, end).replace('export ', ''), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return new Function(`${compiled}\nreturn apiErrorMessage;`)();
}

test('a FastAPI 422 body is shown as its messages, not "[object Object]"', async () => {
  const apiErrorMessage = await loadApiErrorMessage();
  const body = { detail: [
    { type: 'greater_than', loc: ['query', 'pValueThreshold'], msg: 'Input should be greater than 0', input: '0' },
    { type: 'less_than_equal', loc: ['query', 'pValueThreshold'], msg: 'Input should be less than or equal to 1', input: '2' },
  ] };
  assert.equal(apiErrorMessage(body, 'fallback'),
    'Input should be greater than 0; Input should be less than or equal to 1');
  assert.equal(String(body.detail), '[object Object],[object Object]');
});

test('a plain detail string and a missing body keep the old behaviour', async () => {
  const apiErrorMessage = await loadApiErrorMessage();
  assert.equal(apiErrorMessage({ detail: 'Select two different conditions.' }, 'fallback'), 'Select two different conditions.');
  assert.equal(apiErrorMessage({ detail: '  ' }, 'fallback'), 'fallback');
  assert.equal(apiErrorMessage(null, 'fallback'), 'fallback');
  assert.equal(apiErrorMessage({ other: 1 }, 'fallback'), 'fallback');
  assert.equal(apiErrorMessage({ detail: { code: 'x' } }, 'fallback'), 'fallback');
});

test('every client goes through the one request helper', async () => {
  const source = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8');
  assert.equal(source.includes('String(data.detail)'), false);
  // The four steps -- fetch, parse, test `ok`, raise `apiErrorMessage` -- used to
  // be written out in all 79 clients, which is why the 422 fix had to be applied
  // 79 times. `requestUrl` owns them now. What may still call fetch directly:
  // the helper itself, a status branch (428 consent, 409 restore, 404 -> null),
  // a multipart upload, and the HTML/blob responses that are not JSON.
  const rawFetches = (source.match(/await fetch\(/g) ?? []).length;
  assert.ok(rawFetches <= 8, `api.ts writes ${rawFetches} fetch calls by hand`);
  assert.ok((source.match(/await requestUrl?\(|await request\(/g) ?? []).length > 60);
});
