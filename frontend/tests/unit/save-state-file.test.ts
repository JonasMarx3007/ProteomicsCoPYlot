/**
 * Writing a save file never destroys the previous one.
 *
 * The existing file is replaced only after the new contents were written and
 * the writable closed; a failure at any step aborts the write, keeps the old
 * save and reports the original error, and never falls back to a picker. A
 * cancelled Save As never touches the file that was open.
 *
 * Converted from a node --test file that transpiled the module by hand.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { openRestoreStateFileWithPicker, saveRestoreStateBlob, type SaveStateFileHandle } from "../../src/lib/saveStateFile";

type Failure = "create" | "write" | "close" | "abort" | undefined;

function target(failure?: Failure) {
  let contents = "previous save";
  const calls: string[] = [];
  const error = new Error(`${failure} failed`);
  const handle: SaveStateFileHandle = {
    name: "analysis.copylotstate",
    async createWritable() {
      calls.push("create");
      if (failure === "create") throw error;
      let staged: string | undefined;
      return {
        async write(blob: Blob) {
          calls.push("write");
          staged = await blob.text();
          if (failure === "write" || failure === "abort") throw error;
        },
        async close() {
          calls.push("close");
          if (failure === "close") throw error;
          contents = staged!;
        },
        async abort() {
          calls.push("abort");
          staged = undefined;
          if (failure === "abort") throw new Error("cleanup failed");
        },
      };
    },
  };
  return { handle, calls, error, contents: () => contents };
}

const unexpectedPicker = async () => { throw new Error("Unexpected picker"); };

beforeEach(() => {
  // jsdom, like node, has no File System Access API.
  vi.stubGlobal("showSaveFilePicker", vi.fn(unexpectedPicker));
  vi.stubGlobal("showOpenFilePicker", vi.fn(unexpectedPicker));
});
afterEach(() => vi.unstubAllGlobals());

describe("saving over an existing file", () => {
  it("replaces the existing save only after a successful write and close", async () => {
    const file = target();
    const result = await saveRestoreStateBlob({ blob: new Blob(["new save"]), existingHandle: file.handle });
    expect(result.handle).toBe(file.handle);
    expect(result.method).toBe("handle");
    expect(file.contents()).toBe("new save");
    expect(file.calls).toEqual(["create", "write", "close"]);
  });

  it.each(["create", "write", "close", "abort"] as const)(
    "keeps the previous save and the original error, without a fallback, when %s fails",
    async (failure) => {
      const file = target(failure);
      let picked = false;
      vi.stubGlobal("showSaveFilePicker", async () => { picked = true; return file.handle; });
      const outcome = await saveRestoreStateBlob({ blob: new Blob(["new"]), existingHandle: file.handle }).then(
        () => null, (error: unknown) => error);
      expect(outcome).toBe(file.error);
      expect(file.contents()).toBe("previous save");
      expect(picked).toBe(false);
      expect(file.calls).toEqual(failure === "create" ? ["create"]
        : failure === "close" ? ["create", "write", "close", "abort"] : ["create", "write", "abort"]);
    }
  );
});

describe("Save As", () => {
  it("never opens the existing target for writing when cancelled", async () => {
    const file = target();
    const cancelled = new DOMException("Cancelled", "AbortError");
    vi.stubGlobal("showSaveFilePicker", async () => { throw cancelled; });
    const outcome = await saveRestoreStateBlob({ blob: new Blob(["new"]), existingHandle: file.handle, forcePicker: true })
      .then(() => null, (error: unknown) => error);
    expect(outcome).toBe(cancelled);
    expect(file.calls).toEqual([]);
  });

  it("writes only the explicitly selected new target", async () => {
    const previous = target();
    const selected = target();
    vi.stubGlobal("showSaveFilePicker", async (options: { suggestedName?: string }) => {
      expect(options.suggestedName).toBe("new.copylotstate");
      return selected.handle;
    });
    await saveRestoreStateBlob({ blob: new Blob(["new"]), suggestedName: "new", existingHandle: previous.handle, forcePicker: true });
    expect(previous.calls).toEqual([]);
    expect(selected.contents()).toBe("new");
  });
});

describe("opening a save file", () => {
  it("propagates a cancelled native picker without writing", async () => {
    const cancelled = new DOMException("Cancelled", "AbortError");
    vi.stubGlobal("showOpenFilePicker", async () => { throw cancelled; });
    const outcome = await openRestoreStateFileWithPicker().then(() => null, (error: unknown) => error);
    expect(outcome).toBe(cancelled);
  });

  it("returns the selected file and propagates read failures", async () => {
    const file = new File(["saved"], "state.copylotstate");
    const handle = { async getFile() { return file; } } as unknown as SaveStateFileHandle;
    vi.stubGlobal("showOpenFilePicker", async () => [handle]);
    expect(await openRestoreStateFileWithPicker()).toEqual({ file, handle });
    handle.getFile = async () => { throw new Error("Permission denied"); };
    await expect(openRestoreStateFileWithPicker()).rejects.toThrow(/Permission denied/);
  });
});
