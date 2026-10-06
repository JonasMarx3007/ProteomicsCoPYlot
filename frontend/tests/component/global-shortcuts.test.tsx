/**
 * The two global shortcuts, and what they must leave to the browser.
 *
 * Ctrl/Cmd+S saves the session (not in a viewer); Ctrl/Cmd+Shift+E toggles the
 * advanced plot panel everywhere, the Settings switch included. These press
 * keys instead of reading App.tsx.
 */
import { StrictMode } from "react";
import { act, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getAdvancedPlotMode, setAdvancedPlotMode } from "../../src/lib/appSettings";
import { globalShortcutFor, useGlobalShortcuts } from "../../src/lib/globalShortcuts";
import { silenceNetwork } from "./apiMock";
import SettingsPage from "../../src/features/settings/SettingsPage";

vi.mock("../../src/lib/api", async (original) => (await import("./apiMock")).mockApiModule(original));

const press = (code: string, modifiers: Partial<KeyboardEventInit> = {}) =>
  ({ code, shiftKey: false, ctrlKey: true, metaKey: false, altKey: false, repeat: false, ...modifiers });

describe("which key press is which shortcut", () => {
  const analysis = { viewerMode: false };
  it.each([
    ["Ctrl+S", press("KeyS"), "quickSave"],
    ["Cmd+S", press("KeyS", { ctrlKey: false, metaKey: true }), "quickSave"],
    ["Ctrl+Shift+E", press("KeyE", { shiftKey: true }), "toggleAdvancedPlots"],
    ["Ctrl+Shift+S (the browser's)", press("KeyS", { shiftKey: true }), null],
    ["Ctrl+Shift+A (Chrome's tab search)", press("KeyA", { shiftKey: true }), null],
    ["Ctrl+E without Shift", press("KeyE"), null],
    ["Alt+Ctrl+S", press("KeyS", { altKey: true }), null],
    ["S alone", press("KeyS", { ctrlKey: false }), null],
    ["a held Ctrl+S", press("KeyS", { repeat: true }), null],
  ])("%s", (_label, event, expected) => {
    expect(globalShortcutFor(event as KeyboardEvent, analysis)).toBe(expected);
  });

  it("matches the physical key, whatever letter the layout prints on it", () => {
    // On AZERTY the key at QWERTY's A prints "q": `code` stays "KeyA".
    expect(globalShortcutFor({ ...press("KeyS"), key: "ß" } as unknown as KeyboardEvent, analysis)).toBe("quickSave");
    expect(globalShortcutFor({ ...press("KeyD"), key: "s" } as unknown as KeyboardEvent, analysis)).toBe(null);
  });

  it("leaves quick save out of a viewer but keeps the advanced toggle", () => {
    expect(globalShortcutFor(press("KeyS") as KeyboardEvent, { viewerMode: true })).toBe(null);
    expect(globalShortcutFor(press("KeyE", { shiftKey: true }) as KeyboardEvent, { viewerMode: true })).toBe("toggleAdvancedPlots");
  });
});

describe("the global listener", () => {
  beforeEach(() => setAdvancedPlotMode(false));

  it("saves once per press and keeps the browser's own save dialog closed", () => {
    const save = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useGlobalShortcuts(save, { viewerMode: false }), { wrapper: StrictMode });
    const notCancelled = fireEvent.keyDown(window, { code: "KeyS", key: "s", ctrlKey: true });
    expect(save).toHaveBeenCalledTimes(1);
    expect(notCancelled).toBe(false);
  });

  it("does not save in a viewer", () => {
    const save = vi.fn().mockResolvedValue(undefined);
    renderHook(() => useGlobalShortcuts(save, { viewerMode: true }), { wrapper: StrictMode });
    fireEvent.keyDown(window, { code: "KeyS", key: "s", ctrlKey: true });
    expect(save).not.toHaveBeenCalled();
  });

  it("toggles the advanced plot mode through the shared, broadcasting setter", () => {
    const heard = vi.fn();
    window.addEventListener("copylot:advancedPlotModeChanged", heard);
    renderHook(() => useGlobalShortcuts(vi.fn().mockResolvedValue(undefined), { viewerMode: false }), { wrapper: StrictMode });
    fireEvent.keyDown(window, { code: "KeyE", key: "E", ctrlKey: true, shiftKey: true });
    expect(getAdvancedPlotMode()).toBe(true);
    expect(heard).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(window, { code: "KeyE", key: "E", ctrlKey: true, shiftKey: true });
    expect(getAdvancedPlotMode()).toBe(false);
    window.removeEventListener("copylot:advancedPlotModeChanged", heard);
  });
});

describe("the Settings switch", () => {
  beforeEach(() => {
    silenceNetwork();
    setAdvancedPlotMode(false);
  });

  it("names the shortcut and follows it while the page is open", async () => {
    render(<StrictMode><SettingsPage /></StrictMode>);
    const toggle = screen.getByRole("checkbox", { name: /Advanced plot option mode/ });
    expect(screen.getByText(/Ctrl\/Cmd \+ Shift \+ E/)).toBeTruthy();
    expect((toggle as HTMLInputElement).checked).toBe(false);
    act(() => setAdvancedPlotMode(true));
    expect((toggle as HTMLInputElement).checked).toBe(true);
  });
});
