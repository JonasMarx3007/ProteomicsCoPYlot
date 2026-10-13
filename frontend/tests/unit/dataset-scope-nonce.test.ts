/**
 * After a call that changes a matrix, every plot and table URL is new.
 *
 * Every response is a function of the session's current matrices, and those
 * change under the same URL: re-filtering or re-imputing rewrites every number
 * without moving an endpoint. The backend says `no-store` on everything under
 * /api/ (tests/integration/api/test_no_stale_answers.py); this is the other
 * half. `buildPlotUrl` appends `_dsn`, a nonce that every call replacing a
 * matrix bumps -- seven of them once did not, including `generateAnnotation`
 * (re-filtering and re-normalising) and `runImputation`. A call that fails has
 * changed nothing, so it leaves the URLs alone.
 *
 * Each client is called against a backend that accepts or refuses it, and the
 * URL `buildPlotUrl` builds is compared before and after. This replaced Python
 * checks that sliced each function's body out of api.ts and searched it for
 * `bumpDatasetScopeNonce()`.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/lib/api";
import { TAB_API_BASE } from "../../src/lib/tabSession";

// Calls that replace, rebuild or re-scope a matrix.
const MUST_BUMP = [
  "uploadDataset", "saveTableDatasetPath", "importRestoreState", "savePeptidePath", "uploadPeptideFile",
  "createDatasetPackage", "renameDatasetPackage", "setActiveDatasetPackage", "createMetadataProfile",
  "deleteMetadataProfile", "renameMetadataProfile", "setActiveMetadataProfile", "updateAnnotationPairing",
  "uploadAnnotationMetadata", "generateAnnotation", "runImputation", "aggregatePhosprot", "setConditionPalette",
  "generatePeptideMetadata",
] as const;

// Reads and analyses: they change no matrix, so they leave every URL as it was.
const MUST_NOT_BUMP = ["getCurrentDatasets", "getStatisticalOptions", "runVolcanoAnalysis", "getQcPlotOptions"] as const;

type Client = (...args: unknown[]) => Promise<unknown>;
const client = (name: string) => (api as unknown as Record<string, Client>)[name];

function answer(status: number) {
  vi.stubGlobal("fetch", vi.fn(async () =>
    new Response(status === 200 ? "{}" : JSON.stringify({ detail: "Refused" }), { status, headers: { "Content-Type": "application/json" } })));
}

async function call(name: string) {
  const fn = client(name);
  // A string for every argument is enough for each client to reach the network.
  return fn(...Array.from({ length: Math.max(fn.length, 1) }, () => "protein")).then(() => null, (error: unknown) => error);
}

const nonce = () => new URL(api.buildPlotUrl("/api/plots/qc/protein/cv.png", { dpi: 300 }), "http://localhost").searchParams.get("_dsn");

afterEach(() => vi.unstubAllGlobals());

describe("plot URL boundaries", () => {
  it.each(["javascript:alert(1)", "//elsewhere.invalid/api/x", "/api/../private", "/api/plots/./x"])(
    "rejects paths outside the API: %s", (path) => {
      expect(() => api.buildPlotUrl(path)).toThrow("application API");
    },
  );

  it("encodes path segments and query values without changing ordinary routes", () => {
    const normal = new URL(api.buildPlotUrl("/api/plots/qc/protein/cv.png"), "https://example.org");
    expect(normal.pathname).toBe(`${TAB_API_BASE}/api/plots/qc/protein/cv.png`);
    const url = new URL(api.buildPlotUrl('/api/plots/a?b#c"<d>%.png', { title: '<img src=x onerror="alert(1)">' }), "https://example.org");
    expect(url.origin).toBe(normal.origin);
    expect(url.hash).toBe("");
    expect(decodeURIComponent(url.pathname)).toBe(`${TAB_API_BASE}/api/plots/a?b#c"<d>%.png`);
    expect(url.searchParams.get("title")).toBe('<img src=x onerror="alert(1)">');
    expect(url.searchParams.has("b")).toBe(false);
  });
});

describe("the dataset-scope nonce", () => {
  it("is part of every plot URL", () => {
    expect(nonce()).toMatch(/^\d+$/);
  });

  it.each(MUST_BUMP)("changes when %s succeeds", async (name) => {
    answer(200);
    const before = nonce();
    expect(await call(name)).toBeNull();
    expect(nonce()).not.toBe(before);
  });

  it.each(MUST_BUMP)("stays when %s is refused, since nothing changed", async (name) => {
    answer(400);
    const before = nonce();
    expect(await call(name)).toBeInstanceOf(Error);
    expect(nonce()).toBe(before);
  });

  it.each(MUST_NOT_BUMP)("stays when %s only reads", async (name) => {
    answer(200);
    const before = nonce();
    await call(name);
    expect(nonce()).toBe(before);
  });
});
