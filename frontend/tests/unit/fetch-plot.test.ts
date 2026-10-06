/**
 * Plot requests retry a temporarily busy server, and nothing else.
 *
 * A 503 with a short Retry-After is the backend saying "rendering queue full,
 * ask again"; the request is repeated after that delay, at most three times,
 * with the same URL and abort signal. A refusal (422), a crash (500), a missing
 * or unreasonable Retry-After and a network failure are answers, not retries,
 * and changing the view cancels a pending retry without another request.
 *
 * Converted from a node --test file that compiled the module with stubbed
 * timers; the timers are spied on here instead.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchPlot } from "../../src/lib/fetchPlot";

const busy = (value: string | null = "2") =>
  new Response("busy", { status: 503, headers: value === null ? {} : { "Retry-After": value } });

type Timer = (callback: () => void, delay: number) => unknown;

function serve(fetch: (url: string, options: RequestInit) => Promise<Response>, timer: Timer, clear: (id: unknown) => void = () => {}) {
  vi.stubGlobal("fetch", vi.fn(fetch));
  vi.spyOn(globalThis, "setTimeout").mockImplementation(timer as unknown as typeof setTimeout);
  vi.spyOn(globalThis, "clearTimeout").mockImplementation(clear as unknown as typeof clearTimeout);
}

const soon: Timer = (callback) => { queueMicrotask(callback); return 0; };
const never: Timer = () => { throw new Error("Unexpected retry"); };

afterEach(() => vi.unstubAllGlobals());

describe("fetchPlot", () => {
  it("recovers from temporary busy responses, keeping the URL and the abort signal", async () => {
    const controller = new AbortController();
    const delays: number[] = [];
    let calls = 0;
    const success = new Response("plot", { headers: { "X-CoPYlot-Notebook": "snapshot" } });
    serve(async (url, options) => {
      expect(url).toBe("/plot?width=20");
      expect(options.signal).toBe(controller.signal);
      return ++calls < 3 ? busy() : success;
    }, (callback, delay) => { delays.push(delay); queueMicrotask(callback); return 0; });
    expect(await fetchPlot("/plot?width=20", controller.signal)).toBe(success);
    expect(delays).toEqual([2000, 2000]);
    expect(calls).toBe(3);
  });

  it("stops after three retries of a persistent busy response and keeps the final error body", async () => {
    let calls = 0;
    serve(async () => { calls++; return busy("0"); }, soon);
    const result = await fetchPlot("/plot", new AbortController().signal);
    expect(calls).toBe(4);
    expect(await result.text()).toBe("busy");
  });

  it("does not retry scientific refusals, permanent errors, invalid headers or long delays", async () => {
    for (const response of [new Response("no data", { status: 422 }), new Response("error", { status: 500 }),
      busy(null), busy("nonsense"), busy("60"), busy("Infinity"), busy("-1"), busy("1.5"), new Response("plot")]) {
      let calls = 0;
      serve(async () => { calls++; return response; }, never);
      expect(await fetchPlot("/plot", new AbortController().signal)).toBe(response);
      expect(calls).toBe(1);
    }
  });

  it("respects an HTTP-date retry delay without hot looping", async () => {
    let calls = 0;
    serve(async () => ++calls === 1 ? busy(new Date(Date.now() + 5000).toUTCString()) : new Response(),
      (callback, delay) => { expect(delay).toBeGreaterThanOrEqual(3000); expect(delay).toBeLessThanOrEqual(5000); queueMicrotask(callback); return 0; });
    await fetchPlot("/plot", new AbortController().signal);
    expect(calls).toBe(2);
  });

  it("cancels the pending retry without another request when the view changes", async () => {
    const controller = new AbortController();
    let scheduled: (() => void) | undefined;
    let calls = 0;
    let cleared = false;
    serve(async () => { calls++; return busy(); }, (callback) => { scheduled = callback; return 17; },
      (timer) => { expect(timer).toBe(17); cleared = true; });
    const result = fetchPlot("/old-plot", controller.signal);
    while (!scheduled) await new Promise((resolve) => queueMicrotask(() => resolve(null)));
    controller.abort();
    await expect(result).rejects.toMatchObject({ name: "AbortError" });
    expect(calls).toBe(1);
    expect(cleared).toBe(true);
    scheduled();
    expect(calls).toBe(1);
  });

  it("does not retry an already aborted request or a network failure", async () => {
    const controller = new AbortController();
    controller.abort();
    serve(async () => { throw new Error("offline"); }, never);
    await expect(fetchPlot("/plot", controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    await expect(fetchPlot("/plot", new AbortController().signal)).rejects.toThrow(/offline/);
  });
});
