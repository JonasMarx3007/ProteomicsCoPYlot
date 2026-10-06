/**
 * Builds ship the manuals the app opens, and nothing else from public/manuals.
 *
 * public/manuals also keeps the editable .docx sources and PDFs no page opens
 * (about 6.5 MB). vite.config.ts drops everything App does not link after the
 * build, by reading App's `manualPath(...)` calls. This walks every section
 * and tab of the mounted app, opens each manual it offers, and checks both
 * sides: every manual the app opens exists, and the build keeps exactly those.
 *
 * It replaced Python regular expressions over App.tsx and vite.config.ts
 * (tests/repo/test_shipped_manuals.py, which was deleted with them).
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { cpSync, existsSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import type { Plugin } from "vite";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import App from "../../src/App";
import * as api from "../../src/lib/api";
import viteConfig from "../../vite.config";
import { serveDatasets, silenceNetwork } from "../component/apiMock";

vi.mock("../../src/lib/api", async (original) => (await import("../component/apiMock")).mockApiModule(original));

const FRONTEND = resolve(__dirname, "../..");
const MANUALS = join(FRONTEND, "public", "manuals");

/** Every manual the app opens, by file name, found by visiting every view. */
const opened = new Set<string>();

beforeAll(() => {
  // jsdom has no modal dialogs.
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) { this.open = true; });
  HTMLDialogElement.prototype.close = vi.fn(function (this: HTMLDialogElement) { this.open = false; });
  silenceNetwork();
  serveDatasets(api);
  render(<App />);
  const sidebar = screen.getByRole("navigation", { name: "Analysis modules" });
  for (const section of within(sidebar).getAllByRole("button").map((button) => button.textContent!)) {
    fireEvent.click(within(screen.getByRole("navigation", { name: "Analysis modules" })).getByRole("button", { name: section }));
    const views = screen.queryByRole("navigation", { name: "Module views" });
    const tabs = views ? within(views).getAllByRole("button").map((button) => button.textContent!) : [""];
    for (const tab of tabs) {
      if (tab) fireEvent.click(within(screen.getByRole("navigation", { name: "Module views" })).getByRole("button", { name: tab }));
      const manual = screen.queryByRole("button", { name: "Manual" });
      if (!manual) continue;
      fireEvent.click(manual);
      const href = screen.getByRole("link", { name: "Open" }).getAttribute("href")!;
      opened.add(decodeURIComponent(href.split("/").at(-1)!));
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
    }
  }
}, 30_000);

describe("the manuals", () => {
  it("are offered by the app's views", () => {
    // One per plot view that has one; a regression to none would pass the rest.
    expect(opened.size).toBeGreaterThan(15);
  });

  it("the app opens all exist in public/manuals", () => {
    expect([...opened].filter((name) => !existsSync(join(MANUALS, name)))).toEqual([]);
  });

  describe("in a build", () => {
    let outDir = "";
    beforeAll(() => {
      outDir = mkdtempSync(join(tmpdir(), "copylot-manuals-"));
      cpSync(MANUALS, join(outDir, "manuals"), { recursive: true });
    });
    afterAll(() => rmSync(outDir, { recursive: true, force: true }));

    it("are exactly the ones the app opens", () => {
      const plugin = (viteConfig.plugins ?? []).flat().find(
        (candidate): candidate is Plugin => Boolean(candidate) && (candidate as Plugin).name === "copylot-linked-manuals-only"
      );
      expect(plugin, "the build no longer filters the manuals").toBeDefined();
      const call = (hook: unknown, ...args: unknown[]) => (hook as (...a: unknown[]) => void).apply({}, args);
      call(plugin!.configResolved, { root: FRONTEND, build: { outDir } });
      call(plugin!.closeBundle);
      expect(readdirSync(join(outDir, "manuals")).sort()).toEqual([...opened].sort());
    });
  });
});
