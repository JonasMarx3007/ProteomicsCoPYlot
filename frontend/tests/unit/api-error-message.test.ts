/**
 * An error from the backend reaches the page as its message.
 *
 * FastAPI answers a validation failure (422) with `{"detail": [{"msg": ...}]}`,
 * and `String()` of that list is "[object Object]" -- which is what every page
 * showed for a p-value of 0. `apiErrorMessage` reads either shape, and the one
 * request helper in api.ts raises it for every client.
 *
 * This replaced a check that counted `await fetch(` and `await request(` in the
 * source of api.ts. Here every exported client is called against a backend that
 * refuses with a 422, and the error each one raises is read.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../../src/lib/api";
import { apiErrorMessage } from "../../src/lib/api";

describe("apiErrorMessage", () => {
  it('shows a FastAPI 422 body as its messages, not "[object Object]"', () => {
    const body = { detail: [
      { type: "greater_than", loc: ["query", "pValueThreshold"], msg: "Input should be greater than 0", input: "0" },
      { type: "less_than_equal", loc: ["query", "pValueThreshold"], msg: "Input should be less than or equal to 1", input: "2" },
    ] };
    expect(apiErrorMessage(body, "fallback")).toBe("Input should be greater than 0; Input should be less than or equal to 1");
    expect(String(body.detail)).toBe("[object Object],[object Object]");
  });

  it("keeps the old behaviour for a plain detail string and a missing body", () => {
    expect(apiErrorMessage({ detail: "Select two different conditions." }, "fallback")).toBe("Select two different conditions.");
    expect(apiErrorMessage({ detail: "  " }, "fallback")).toBe("fallback");
    expect(apiErrorMessage(null, "fallback")).toBe("fallback");
    expect(apiErrorMessage({ other: 1 }, "fallback")).toBe("fallback");
    expect(apiErrorMessage({ detail: { code: "x" } }, "fallback")).toBe("fallback");
  });
});

// Clients that answer a failure in their own words on purpose.
const OWN_ERROR_PATH: Record<string, string> = {
  // The assistant shows a plain-string detail and otherwise its own sentence.
  assistantStep: "The assistant could not complete this step.",
};
// Clients that do not yet show a 422 readably. Each is a product defect; the
// entry is removed when it is fixed.
const KNOWN_DEFECTS = new Set<string>([]);

afterEach(() => vi.unstubAllGlobals());

describe("every API client", () => {
  const clients = Object.entries(api).filter(
    (entry): entry is [string, (...args: unknown[]) => Promise<unknown>] =>
      typeof entry[1] === "function" && entry[1].constructor.name === "AsyncFunction"
  );

  it("is found, so the check below covers the whole module", () => {
    expect(clients.length).toBeGreaterThan(80);
  });

  it.each(clients.filter(([name]) => !KNOWN_DEFECTS.has(name)))(
    "%s raises the messages of a 422 body",
    async (name, client) => {
      const body = { detail: [{ msg: "First problem", input: "private" }, { msg: "Second problem" }] };
      vi.stubGlobal("fetch", vi.fn(async () =>
        new Response(JSON.stringify(body), { status: 422, headers: { "Content-Type": "application/json" } })));
      // Every client builds its request from its arguments; a string is enough
      // for each to reach the network, which is all this needs.
      const args = Array.from({ length: Math.max(client.length, 1) }, () => "protein");
      const error = await client(...args).then(() => null, (reason: unknown) => reason);
      expect(error, `${name} resolved on a 422`).toBeInstanceOf(Error);
      expect((error as Error).message).toBe(OWN_ERROR_PATH[name] ?? "First problem; Second problem");
    }
  );
});
