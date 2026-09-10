import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

async function loadModule(name) {
  const source = await readFile(new URL(`../src/lib/${name}.ts`, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
}
const { UnsavedAnalysis, isAnalysisMutation, warnBeforeUnload } = await loadModule("unsavedAnalysis");
const { onceAsync } = await loadModule("onceAsync");

test("initial state is clean; UI changes warn and reverting them is clean", () => {
  const state = new UnsavedAnalysis();
  state.initialize({ a: 1, b: 2 });
  assert.equal(state.isDirty({ b: 2, a: 1 }), false);
  assert.equal(state.isDirty({ a: 2, b: 2 }), true);
  assert.equal(state.isDirty({ a: 1, b: 2 }), false);
});

test("a completed save clears only the captured state", () => {
  const state = new UnsavedAnalysis();
  state.initialize({});
  state.beginMutation()();
  assert.equal(state.isDirty({}), true);
  const checkpoint = state.capture({ settings: 2 });
  state.markSaved(checkpoint);
  assert.equal(state.isDirty({ settings: 2 }), false);
  assert.equal(state.isDirty({ settings: 3 }), true);
});

test("edits during export or writing cannot be declared saved", () => {
  const state = new UnsavedAnalysis();
  state.initialize({});
  const checkpoint = state.capture({});
  state.beginMutation()();
  state.markSaved(checkpoint);
  assert.equal(state.isDirty({}), true);
});

test("saving while a mutation is pending stays dirty even after completion", () => {
  const state = new UnsavedAnalysis();
  state.initialize({});
  const finish = state.beginMutation();
  const checkpoint = state.capture({});
  finish(); finish();
  state.markSaved(checkpoint);
  assert.equal(state.isDirty({}), true);
  state.markSaved(state.capture({}));
  assert.equal(state.isDirty({}), false);
});

test("failed/cancelled save or unconfirmed download leaves dirty state", () => {
  const state = new UnsavedAnalysis();
  state.initialize({});
  state.beginMutation()();
  state.capture({}); // No successful write/confirmation -> no markSaved.
  assert.equal(state.isDirty({}), true);
});

test("beforeunload asks without changing the saved/analysis state", () => {
  const state = new UnsavedAnalysis();
  state.initialize({});
  state.beginMutation()();
  let prevented = 0;
  const event = { preventDefault() { prevented++; }, returnValue: undefined };
  warnBeforeUnload(event, false);
  assert.equal(prevented, 0);
  warnBeforeUnload(event, state.isDirty({}));
  assert.equal(prevented, 1);
  assert.equal(event.returnValue, true);
  assert.equal(state.isDirty({}), true); // User cancelling cannot trigger reset/save.
});

for (const path of ["datasets/upload", "datasets/active", "annotations/generate", "annotations/pairing", "annotations/phosprot/aggregate", "annotations/metadata/current/phospho", "peptide/metadata/generate", "data-tools/imputation/run", "data-tools/id-translation/run", "data-tools/condition-colors/protein", "restore/import"]) {
  test(`tracks persisted mutation ${path}`, () => assert.equal(isAnalysisMutation(`/api/${path}`, "POST"), true));
}
for (const path of ["restore/export", "restore/browser-session-reset", "stats/volcano/run", "annotations/log2-detect", "data-tools/imputation/download", "data-tools/id-translation/download", "tool/auth/login", "chat/module-context"]) {
  test(`does not dirty analysis for read/auth/export ${path}`, () => assert.equal(isAnalysisMutation(`/api/${path}`, "POST"), false));
}
test("GET requests never count as mutations", () => assert.equal(isAnalysisMutation("/api/annotations/current/phospho"), false));

test("all concurrent initialization consumers wait for one reset", async () => {
  let complete;
  let calls = 0;
  let reads = 0;
  const barrier = new Promise((resolve) => { complete = resolve; });
  const initialize = onceAsync(async () => { calls++; await barrier; });
  const first = initialize();
  const second = initialize();
  assert.equal(first, second);
  const consumers = [first.then(() => reads++), second.then(() => reads++)];
  await Promise.resolve();
  assert.equal(calls, 1);
  assert.equal(reads, 0);
  complete();
  await Promise.all(consumers);
  assert.equal(reads, 2);
  await initialize();
  assert.equal(calls, 1); // Remount/StrictMode never resets again.
});

test("reset failure blocks every consumer instead of opening stale state", async () => {
  let calls = 0;
  const initialize = onceAsync(async () => { calls++; throw new Error("reset failed"); });
  await assert.rejects(initialize(), /reset failed/);
  await assert.rejects(initialize(), /reset failed/);
  assert.equal(calls, 1);
});
