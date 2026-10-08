/**
 * public/manuals holds exactly the manual the app opens: one chapter PDF per
 * page with a tab bar, and the complete book every chapter dialog links to.
 *
 * This walks every section and tab of the mounted app, opens each manual it
 * offers, and checks both sides: every manual the app opens exists, and
 * nothing else ships (no editable sources, no stale PDFs).
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { existsSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { beforeAll, describe, expect, it, vi } from "vitest";
import App from "../../src/App";
import * as api from "../../src/lib/api";
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
      for (const name of ["Open", "Complete manual"]) {
        const href = screen.getByRole("link", { name }).getAttribute("href")!;
        opened.add(decodeURIComponent(href.split("/").at(-1)!));
      }
      fireEvent.click(screen.getByRole("button", { name: "Close" }));
    }
  }
}, 30_000);

describe("the manuals", () => {
  it("are offered by the app's views", () => {
    // One per view with a tab bar, plus the complete manual.
    expect(opened.size).toBeGreaterThan(40);
  });

  it("the app opens all exist in public/manuals", () => {
    expect([...opened].filter((name) => !existsSync(join(MANUALS, name)))).toEqual([]);
  });

  it("are all that public/manuals holds", () => {
    expect(readdirSync(MANUALS).sort()).toEqual([...opened].sort());
  });
});
