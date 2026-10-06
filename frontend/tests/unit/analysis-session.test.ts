/**
 * The unsaved-analysis tracker and the one-time session reset.
 *
 * The browser warns before leaving only when the analysis has changed since it
 * was last saved, and a save is credited only with the state it captured: an
 * edit made while the file was being written is still unsaved. The session reset
 * runs once however many consumers ask for it, and a failed reset blocks them
 * all rather than letting one read stale state.
 *
 * Converted from a node --test file that transpiled the modules by hand.
 */
import { describe, expect, it } from "vitest";
import { onceAsync } from "../../src/lib/onceAsync";
import { isAnalysisMutation, UnsavedAnalysis, warnBeforeUnload } from "../../src/lib/unsavedAnalysis";

describe("the unsaved-analysis state", () => {
  it("is clean initially, warns after a UI change and is clean again once the change is reverted", () => {
    const state = new UnsavedAnalysis();
    state.initialize({ a: 1, b: 2 });
    expect(state.isDirty({ b: 2, a: 1 })).toBe(false);
    expect(state.isDirty({ a: 2, b: 2 })).toBe(true);
    expect(state.isDirty({ a: 1, b: 2 })).toBe(false);
  });

  it("clears only the captured state when a save completes", () => {
    const state = new UnsavedAnalysis();
    state.initialize({});
    state.beginMutation()();
    expect(state.isDirty({})).toBe(true);
    const checkpoint = state.capture({ settings: 2 });
    state.markSaved(checkpoint);
    expect(state.isDirty({ settings: 2 })).toBe(false);
    expect(state.isDirty({ settings: 3 })).toBe(true);
  });

  it("cannot declare edits made during export or writing saved", () => {
    const state = new UnsavedAnalysis();
    state.initialize({});
    const checkpoint = state.capture({});
    state.beginMutation()();
    state.markSaved(checkpoint);
    expect(state.isDirty({})).toBe(true);
  });

  it("stays dirty after saving while a mutation was pending, even once it completes", () => {
    const state = new UnsavedAnalysis();
    state.initialize({});
    const finish = state.beginMutation();
    const checkpoint = state.capture({});
    finish(); finish();
    state.markSaved(checkpoint);
    expect(state.isDirty({})).toBe(true);
    state.markSaved(state.capture({}));
    expect(state.isDirty({})).toBe(false);
  });

  it("stays dirty after a failed or cancelled save or an unconfirmed download", () => {
    const state = new UnsavedAnalysis();
    state.initialize({});
    state.beginMutation()();
    state.capture({}); // No successful write or confirmation, so no markSaved.
    expect(state.isDirty({})).toBe(true);
  });

  it("asks before unload without changing the saved or analysis state", () => {
    const state = new UnsavedAnalysis();
    state.initialize({});
    state.beginMutation()();
    let prevented = 0;
    const event = { preventDefault() { prevented++; }, returnValue: undefined as unknown } as unknown as BeforeUnloadEvent;
    warnBeforeUnload(event, false);
    expect(prevented).toBe(0);
    warnBeforeUnload(event, state.isDirty({}));
    expect(prevented).toBe(1);
    expect(event.returnValue).toBe(true);
    expect(state.isDirty({})).toBe(true); // Cancelling cannot trigger a reset or a save.
  });
});

describe("which requests change the analysis", () => {
  const MUTATIONS = ["datasets/upload", "datasets/active", "annotations/generate", "annotations/pairing",
    "annotations/phosprot/aggregate", "annotations/metadata/current/phospho", "peptide/metadata/generate",
    "data-tools/imputation/run", "data-tools/id-translation/run", "data-tools/condition-colors/protein", "restore/import"];
  const READS = ["restore/export", "restore/browser-session-reset", "stats/volcano/run", "annotations/log2-detect",
    "data-tools/imputation/download", "data-tools/id-translation/download", "tool/auth/login", "chat/assistant"];

  it.each(MUTATIONS)("tracks the persisted mutation %s", (path) => {
    expect(isAnalysisMutation(`/api/${path}`, "POST")).toBe(true);
  });

  it.each(READS)("does not dirty the analysis for the read, auth or export call %s", (path) => {
    expect(isAnalysisMutation(`/api/${path}`, "POST")).toBe(false);
  });

  it("never counts a GET request as a mutation", () => {
    expect(isAnalysisMutation("/api/annotations/current/phospho")).toBe(false);
  });
});

describe("the one-time session reset", () => {
  it("makes every concurrent consumer wait for one reset", async () => {
    let complete!: () => void;
    let calls = 0;
    let reads = 0;
    const barrier = new Promise<void>((resolve) => { complete = resolve; });
    const initialize = onceAsync(async () => { calls++; await barrier; });
    const first = initialize();
    const second = initialize();
    expect(first).toBe(second);
    const consumers = [first.then(() => reads++), second.then(() => reads++)];
    await Promise.resolve();
    expect(calls).toBe(1);
    expect(reads).toBe(0);
    complete();
    await Promise.all(consumers);
    expect(reads).toBe(2);
    await initialize();
    expect(calls).toBe(1); // A remount or StrictMode never resets again.
  });

  it("blocks every consumer after a failed reset instead of opening stale state", async () => {
    let calls = 0;
    const initialize = onceAsync(async () => { calls++; throw new Error("reset failed"); });
    await expect(initialize()).rejects.toThrow(/reset failed/);
    await expect(initialize()).rejects.toThrow(/reset failed/);
    expect(calls).toBe(1);
  });
});
