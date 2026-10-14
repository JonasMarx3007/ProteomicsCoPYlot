// @vitest-environment node
/**
 * The build writes its mode into the bundle, spelled as the app reads it.
 *
 * The analysis and viewer UIs are two builds of the same source, separated
 * only by `VITE_APP_MODE`, which is baked in and invisible afterwards. A viewer
 * backend serving the analysis bundle shows a viewer with no gating at all, so
 * vite.config.ts emits `build-mode.json` and the launcher refuses a mismatch
 * (tests/repo/test_frontend_bundle_mode.py). The marker is only worth having if
 * it says what the app itself decided: one spelling apart, and the guard passes
 * while the UI stays ungated.
 *
 * Each spelling below is given to both the build config and lib/appMode, and
 * what the build emits is compared with what the app reads. This replaced
 * Python checks for literal strings in vite.config.ts and appMode.ts.
 */
import type { Plugin } from "vite";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

/** What a build emits as build-mode.json under this environment. */
async function emittedMarker() {
  vi.resetModules();
  const config = (await import("../../vite.config")).default;
  const plugin = (config.plugins ?? []).flat().find(
    (candidate): candidate is Plugin => Boolean(candidate) && (candidate as Plugin).name === "copylot-build-mode"
  );
  expect(plugin, "the build no longer writes the marker").toBeDefined();
  expect(plugin!.apply).toBe("build");
  const emitted: { fileName?: string; source?: unknown }[] = [];
  (plugin!.generateBundle as unknown as (this: unknown) => void).call({ emitFile: (file: { fileName?: string; source?: unknown }) => emitted.push(file) });
  const marker = emitted.find((file) => file.fileName === "build-mode.json");
  expect(marker, "build-mode.json is not emitted").toBeDefined();
  return JSON.parse(String(marker!.source)) as { appMode: string; aiEnabled: boolean };
}

async function vitePlugin(name: string) {
  vi.resetModules();
  const config = (await import("../../vite.config")).default;
  const plugin = (config.plugins ?? []).flat().find(
    (candidate): candidate is Plugin => Boolean(candidate) && (candidate as Plugin).name === name
  );
  expect(plugin, `Vite plugin ${name} is missing`).toBeDefined();
  return plugin!;
}

/** The mode the app reads under this environment. */
async function appMode() {
  vi.resetModules();
  return (await import("../../src/lib/appMode")).APP_MODE;
}

const SPELLINGS: [string | undefined, "viewer" | "analysis"][] = [
  ["viewer", "viewer"], [" Viewer ", "viewer"], ["VIEWER", "viewer"],
  ["analysis", "analysis"], ["", "analysis"], [undefined, "analysis"], ["viewers", "analysis"], ["view", "analysis"],
];

describe("the build-mode marker", () => {
  it.each(SPELLINGS)("says the same as the app for VITE_APP_MODE=%j", async (value, expected) => {
    if (value === undefined) vi.stubEnv("VITE_APP_MODE", undefined as unknown as string);
    else vi.stubEnv("VITE_APP_MODE", value);
    const marker = await emittedMarker();
    expect(marker.appMode).toBe(expected);
    expect(await appMode()).toBe(expected);
  });

  it("records whether AI is enabled", async () => {
    vi.stubEnv("VITE_AI_ENABLED", "yes");
    expect((await emittedMarker()).aiEnabled).toBe(true);
    vi.stubEnv("VITE_AI_ENABLED", "0");
    expect((await emittedMarker()).aiEnabled).toBe(false);
  });
});

describe("the licences page", () => {
  it("is emitted with the production frontend licence link", async () => {
    const plugin = await vitePlugin("copylot-build-mode");
    const emitted: { fileName?: string; source?: unknown }[] = [];
    (plugin.generateBundle as unknown as (this: unknown) => void).call({
      emitFile: (file: { fileName?: string; source?: unknown }) => emitted.push(file),
    });

    const page = emitted.find((file) => file.fileName === "licenses.html");
    expect(page, "licenses.html is not emitted").toBeDefined();
    expect(String(page!.source)).toContain('<a href="THIRD_PARTY_LICENSES.md">Frontend third-party licences</a>');
    expect(String(page!.source)).toContain("GNU GENERAL PUBLIC LICENSE");
  });

  it("serves the page in development without promising a missing build asset", async () => {
    const plugin = await vitePlugin("copylot-licenses-dev");
    expect(plugin.apply).toBe("serve");
    let middleware: ((request: { url?: string }, response: {
      setHeader(name: string, value: string): void;
      end(body: string): void;
    }, next: () => void) => void) | undefined;
    (plugin.configureServer as unknown as (server: {
      middlewares: { use(handler: typeof middleware): void };
    }) => void)({ middlewares: { use: (handler) => { middleware = handler; } } });
    expect(middleware).toBeDefined();

    const headers = new Map<string, string>();
    let body = "";
    const next = vi.fn();
    middleware!(
      { url: "/copylot/licenses.html?from=test" },
      { setHeader: (name, value) => headers.set(name, value), end: (value) => { body = value; } },
      next,
    );

    expect(headers.get("Content-Type")).toBe("text/html; charset=utf-8");
    expect(body).toContain("Frontend third-party licences (listed in the production build)");
    expect(body).not.toContain('href="THIRD_PARTY_LICENSES.md"');
    expect(body).toContain("GNU GENERAL PUBLIC LICENSE");
    expect(next).not.toHaveBeenCalled();
  });

  it("leaves unrelated development requests to Vite", async () => {
    const plugin = await vitePlugin("copylot-licenses-dev");
    let middleware: ((request: { url?: string }, response: object, next: () => void) => void) | undefined;
    (plugin.configureServer as unknown as (server: {
      middlewares: { use(handler: typeof middleware): void };
    }) => void)({ middlewares: { use: (handler) => { middleware = handler; } } });
    const next = vi.fn();
    middleware!({ url: "/src/main.tsx" }, {}, next);
    expect(next).toHaveBeenCalledOnce();
  });
});
