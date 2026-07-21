import type { AdvancedPlotSettings } from "./types";
import { IS_VIEWER_MODE } from "./appMode";

export type AppTheme = "light" | "dark";

const ADVANCED_PLOT_MODE_KEY = "copylot:advancedPlotMode";
const ACTIVE_ADVANCED_PLOT_SETTINGS_KEY = "copylot:activeAdvancedPlotSettings";
const ADVANCED_PLOT_SETTINGS_BY_KEY = "copylot:advancedPlotSettingsByKey";

function readString(key: string): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function readSessionString(key: string): string {
  if (typeof window === "undefined") return "";
  try {
    return window.sessionStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function writeString(key: string, value: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignore storage failures; the in-memory UI state still updates.
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

function removeString(key: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(key);
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
  if (!IS_VIEWER_MODE) {
    removeSessionString(ACTIVE_ADVANCED_PLOT_SETTINGS_KEY);
    return;
  }
  removeString(ADVANCED_PLOT_MODE_KEY);
  removeString(ACTIVE_ADVANCED_PLOT_SETTINGS_KEY);
  removeString(ADVANCED_PLOT_SETTINGS_BY_KEY);
  removeSessionString(ADVANCED_PLOT_MODE_KEY);
  removeSessionString(ACTIVE_ADVANCED_PLOT_SETTINGS_KEY);
  removeSessionString(ADVANCED_PLOT_SETTINGS_BY_KEY);
}

export function getAdvancedPlotMode(): boolean {
  if (IS_VIEWER_MODE) return readSessionString(ADVANCED_PLOT_MODE_KEY) === "1";
  return readString(ADVANCED_PLOT_MODE_KEY) === "1";
}

export function setAdvancedPlotMode(enabled: boolean) {
  if (IS_VIEWER_MODE) {
    writeSessionString(ADVANCED_PLOT_MODE_KEY, enabled ? "1" : "0");
    if (!enabled) {
      removeSessionString(ACTIVE_ADVANCED_PLOT_SETTINGS_KEY);
    }
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event("copylot:advancedPlotModeChanged"));
    }
    return;
  }
  writeString(ADVANCED_PLOT_MODE_KEY, enabled ? "1" : "0");
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("copylot:advancedPlotModeChanged"));
  }
}

export function getAdvancedPlotSettingsByKey(): Record<string, AdvancedPlotSettings> {
  const raw = IS_VIEWER_MODE
    ? readSessionString(ADVANCED_PLOT_SETTINGS_BY_KEY)
    : readString(ADVANCED_PLOT_SETTINGS_BY_KEY);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, AdvancedPlotSettings>)
      : {};
  } catch {
    return {};
  }
}

export function setAdvancedPlotSettingsByKey(settings: Record<string, AdvancedPlotSettings>) {
  if (IS_VIEWER_MODE) {
    writeSessionString(ADVANCED_PLOT_SETTINGS_BY_KEY, JSON.stringify(settings));
    return;
  }
  writeString(ADVANCED_PLOT_SETTINGS_BY_KEY, JSON.stringify(settings));
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

export function getActiveAdvancedPlotSettingsJson(): string {
  if (!getAdvancedPlotMode()) return "";
  return readSessionString(ACTIVE_ADVANCED_PLOT_SETTINGS_KEY);
}
