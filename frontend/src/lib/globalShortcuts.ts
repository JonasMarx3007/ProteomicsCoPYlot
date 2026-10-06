import { useEffect, useRef } from "react";

import { getAdvancedPlotMode, setAdvancedPlotMode } from "./appSettings";

export type GlobalShortcut = "quickSave" | "toggleAdvancedPlots";

/**
 * Which of the app's two global shortcuts a key press is, if any.
 *
 * - Ctrl/Cmd is required and Alt is never used: Alt combinations open menus on
 *   Windows and type characters on macOS.
 * - A held key fires once.
 * - `event.code` is the physical key, so the shortcuts fire the same on a QWERTZ
 *   or AZERTY keyboard, where `event.key` for the same key is a different letter.
 * - Shift is part of a shortcut's identity, not a modifier to ignore:
 *   Ctrl+Shift+S is the browser's own, and taking it silently is how a user
 *   loses a screenshot they meant to take.
 * - Quick save is an analysis-mode act: it exports the whole session, which a
 *   viewer neither needs nor may take. The advanced plot toggle stays, so a
 *   collaborator can style a publication-ready figure from a published project.
 * - E, not A, for the advanced panel: Ctrl/Cmd+Shift+A is Chrome's tab search,
 *   and a shortcut the browser answers first is a shortcut the app does not have.
 */
export function globalShortcutFor(
  event: Pick<KeyboardEvent, "code" | "shiftKey" | "ctrlKey" | "metaKey" | "altKey" | "repeat">,
  { viewerMode }: { viewerMode: boolean }
): GlobalShortcut | null {
  if (event.repeat || event.altKey || !(event.ctrlKey || event.metaKey)) return null;
  if (event.code === "KeyS" && !event.shiftKey && !viewerMode) return "quickSave";
  if (event.code === "KeyE" && event.shiftKey) return "toggleAdvancedPlots";
  return null;
}

/** The one global keydown listener: quick save and the advanced plot toggle. */
export function useGlobalShortcuts(onQuickSave: () => Promise<unknown>, { viewerMode }: { viewerMode: boolean }) {
  const quickSave = useRef(onQuickSave);
  useEffect(() => {
    quickSave.current = onQuickSave;
  }, [onQuickSave]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const shortcut = globalShortcutFor(event, { viewerMode });
      if (!shortcut) return;
      event.preventDefault();
      if (shortcut === "quickSave") {
        void quickSave.current().catch(() => {
          // Status is already surfaced through the shared save-state banner.
        });
        return;
      }
      // Same switch as Settings > Advanced plot options: the setter broadcasts,
      // so every page listening picks the change up at once.
      setAdvancedPlotMode(!getAdvancedPlotMode());
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [viewerMode]);
}
