import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/lib/saveStateFile.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText;
const { saveRestoreStateBlob, openRestoreStateFileWithPicker } = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`
);

function target(failure) {
  let contents = 'previous save';
  const calls = [];
  const error = new Error(`${failure} failed`);
  const handle = {
    name: 'analysis.copylotstate',
    async createWritable() {
      calls.push('create');
      if (failure === 'create') throw error;
      let staged;
      return {
        async write(blob) {
          calls.push('write');
          staged = await blob.text();
          if (failure === 'write' || failure === 'abort') throw error;
        },
        async close() {
          calls.push('close');
          if (failure === 'close') throw error;
          contents = staged;
        },
        async abort() {
          calls.push('abort');
          staged = undefined;
          if (failure === 'abort') throw new Error('cleanup failed');
        },
      };
    },
  };
  return { handle, calls, error, contents: () => contents };
}

test('existing save is replaced only after successful write and close', async () => {
  const file = target();
  const result = await saveRestoreStateBlob({ blob: new Blob(['new save']), existingHandle: file.handle });
  assert.equal(result.handle, file.handle);
  assert.equal(result.method, 'handle');
  assert.equal(file.contents(), 'new save');
  assert.deepEqual(file.calls, ['create', 'write', 'close']);
});

for (const failure of ['create', 'write', 'close', 'abort']) {
  test(`${failure} failure preserves previous save and original error without fallback`, async (t) => {
    const file = target(failure);
    let picked = false;
    t.mock.method(globalThis, 'showSaveFilePicker', async () => { picked = true; return file.handle; });
    await assert.rejects(saveRestoreStateBlob({ blob: new Blob(['new']), existingHandle: file.handle }), e => e === file.error);
    assert.equal(file.contents(), 'previous save');
    assert.equal(picked, false);
    assert.deepEqual(file.calls, failure === 'create' ? ['create'] : failure === 'close' ? ['create', 'write', 'close', 'abort'] : ['create', 'write', 'abort']);
  });
}

// Node does not expose these browser-only functions.
globalThis.showSaveFilePicker = async () => { throw new Error('Unexpected picker'); };
globalThis.showOpenFilePicker = async () => { throw new Error('Unexpected picker'); };

test('Save As cancellation never opens the existing target for writing', async (t) => {
  const file = target();
  const cancelled = new DOMException('Cancelled', 'AbortError');
  t.mock.method(globalThis, 'showSaveFilePicker', async () => { throw cancelled; });
  await assert.rejects(saveRestoreStateBlob({ blob: new Blob(['new']), existingHandle: file.handle, forcePicker: true }), e => e === cancelled);
  assert.deepEqual(file.calls, []);
});

test('Save As writes only the explicitly selected new target', async (t) => {
  const previous = target();
  const selected = target();
  t.mock.method(globalThis, 'showSaveFilePicker', async options => {
    assert.equal(options.suggestedName, 'new.copylotstate');
    return selected.handle;
  });
  await saveRestoreStateBlob({ blob: new Blob(['new']), suggestedName: 'new', existingHandle: previous.handle, forcePicker: true });
  assert.deepEqual(previous.calls, []);
  assert.equal(selected.contents(), 'new');
});

test('native open cancellation propagates without writing', async (t) => {
  const cancelled = new DOMException('Cancelled', 'AbortError');
  t.mock.method(globalThis, 'showOpenFilePicker', async () => { throw cancelled; });
  await assert.rejects(openRestoreStateFileWithPicker(), e => e === cancelled);
});

test('native open returns selected file and propagates read failures', async (t) => {
  const file = new File(['saved'], 'state.copylotstate');
  const handle = { async getFile() { return file; } };
  t.mock.method(globalThis, 'showOpenFilePicker', async () => [handle]);
  assert.deepEqual(await openRestoreStateFileWithPicker(), { file, handle });
  handle.getFile = async () => { throw new Error('Permission denied'); };
  await assert.rejects(openRestoreStateFileWithPicker(), /Permission denied/);
});
