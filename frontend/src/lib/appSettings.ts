import { migrateAdvancedSettingsMap } from "./plotSerialization";
import type { AdvancedPlotSettings } from "./types";
import { IS_VIEWER_MODE } from "./appMode";

export type AppTheme = "light" | "dark";

const ADVANCED_PLOT_MODE_KEY = "copylot:advancedPlotMode";
// Versioned. Settings stored before v2 carry every displayed frame and grid
// default the panel used to add to the first edit of anything; applied under
// the current rule -- a setting always applies, advanced mode only shows the
// panel -- they would restyle plots nobody touched. Moving the key drops them
// once, on the first load after the change.
const ACTIVE_ADVANCED_PLOT_SETTINGS_KEY = "copylot:activeAdvancedPlotSettings.v2";
const ADVANCED_PLOT_SETTINGS_BY_KEY = "copylot:advancedPlotSettingsByKey.v2";
const RETIRED_ADVANCED_PLOT_KEYS = [
  "copylot:activeAdvancedPlotSettings",
  "copylot:advancedPlotSettingsByKey",
];

function readSessionString(key: string): string {
  if (typeof window === "undefined") return "";
  try {
    return window.sessionStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function writeSessionString(key: string, value: string) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(key, value);
  } catch {
    // Ignore storage failures; the in-memory UI state still updates.
  }
}

function removeSessionString(key: string) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // Ignore storage failures; the in-memory UI state still updates.
  }
}

export function applyTheme(theme: AppTheme) {
  if (typeof document === "undefined") return;
  document.documentElement.classList.toggle("dark", theme === "dark");
  document.documentElement.dataset.theme = theme;
}

export function getSessionTheme(): AppTheme {
  if (typeof document === "undefined") return "light";
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function setSessionTheme(theme: AppTheme) {
  applyTheme(theme);
}

export function initializeSessionTheme(): AppTheme {
  const theme: AppTheme = "light";
  applyTheme(theme);
  return theme;
}

export function initializeAdvancedPlotState() {
  for (const key of RETIRED_ADVANCED_PLOT_KEYS) removeSessionString(key);
  if (!IS_VIEWER_MODE) {
    removeSessionString(ACTIVE_ADVANCED_PLOT_SETTINGS_KEY);
    return;
  }
  removeSessionString(ADVANCED_PLOT_MODE_KEY);
  removeSessionString(ACTIVE_ADVANCED_PLOT_SETTINGS_KEY);
  removeSessionString(ADVANCED_PLOT_SETTINGS_BY_KEY);
}

export function getAdvancedPlotMode(): boolean {
  return readSessionString(ADVANCED_PLOT_MODE_KEY) === "1";
}

/**
 * Advanced mode shows or hides the appearance panel, and that is all it does.
 *
 * It used to switch the settings off with it: turning the mode off dropped the
 * active settings, so a plot styled in the panel went back to its native look
 * the moment the panel closed, and came back styled when it reopened. The
 * settings are the plot's now, whether the panel that edits them is open or
 * not.
 */
export function setAdvancedPlotMode(enabled: boolean) {
  writeSessionString(ADVANCED_PLOT_MODE_KEY, enabled ? "1" : "0");
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("copylot:advancedPlotModeChanged"));
  }
}

export function getAdvancedPlotSettingsByKey(): Record<string, AdvancedPlotSettings> {
  const raw = readSessionString(ADVANCED_PLOT_SETTINGS_BY_KEY);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (migrateAdvancedSettingsMap(parsed as Record<string, AdvancedPlotSettings>) as Record<string, AdvancedPlotSettings>)
      : {};
  } catch {
    return {};
  }
}

export function setAdvancedPlotSettingsByKey(settings: Record<string, AdvancedPlotSettings>) {
  writeSessionString(ADVANCED_PLOT_SETTINGS_BY_KEY, JSON.stringify(settings));
}

export function setActiveAdvancedPlotSettings(settings: AdvancedPlotSettings | null) {
  if (!settings) {
    removeSessionString(ACTIVE_ADVANCED_PLOT_SETTINGS_KEY);
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("copylot:advancedPlotSettingsChanged"));
    }
    return;
  }
  writeSessionString(ACTIVE_ADVANCED_PLOT_SETTINGS_KEY, JSON.stringify(settings));
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("copylot:advancedPlotSettingsChanged"));
  }
}

/** The active plot's settings, whether or not the panel is open. */
export function getActiveAdvancedPlotSettingsJson(): string {
  return readSessionString(ACTIVE_ADVANCED_PLOT_SETTINGS_KEY);
}
