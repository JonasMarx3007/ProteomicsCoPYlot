// Named plot styles and "this style on every plot".
//
// A style is a plot's appearance settings without its own words: the title,
// axis and legend texts stay with the plot they were written for. Saving
// keeps it for this browser session (like the plot settings themselves);
// applying it to all plots writes it into every plot that already has
// settings and makes it the starting look of plots not opened yet. Only
// appearance settings move -- no data source, selection, test or processing
// setting is part of a style.
import type { AdvancedPlotSettings } from "./types";

const SAVED_KEY = "copylot:savedPlotStyles.v1";
const TEMPLATE_KEY = "copylot:plotStyleTemplate.v1";
const CHANGED = "copylot:plotStylesChanged";

type Store = {
  active: () => AdvancedPlotSettings | null;
  setActive: (settings: AdvancedPlotSettings) => void;
  setAll: (style: AdvancedPlotSettings) => number;
};
const stores = new Map<string, Store>();

function read(key: string): string {
  try { return window.sessionStorage.getItem(key) ?? ""; } catch { return ""; }
}
function write(key: string, value: string) {
  try { window.sessionStorage.setItem(key, value); } catch { /* storage unavailable: the style lives until reload */ }
}

/** The appearance of a plot without its own texts. */
export function styleOf(settings: AdvancedPlotSettings): AdvancedPlotSettings {
  const style: Record<string, unknown> = JSON.parse(JSON.stringify(settings ?? {}));
  for (const element of ["titleElement", "xLabelElement", "yLabelElement"]) {
    const value = style[element];
    if (value && typeof value === "object") delete (value as Record<string, unknown>).text;
  }
  delete style.legendTitle;
  return style as AdvancedPlotSettings;
}

/** A style laid over a plot's settings: its texts are kept. */
export function withStyle(settings: AdvancedPlotSettings | undefined, style: AdvancedPlotSettings): AdvancedPlotSettings {
  const merged: Record<string, unknown> = { ...(settings ?? {}), ...style };
  for (const element of ["titleElement", "xLabelElement", "yLabelElement"] as const) {
    const own = settings?.[element];
    const next = style[element];
    if (own?.text !== undefined || next) merged[element] = { ...(next ?? {}), ...(own?.text !== undefined ? { text: own.text } : {}) };
  }
  if (settings?.legendTitle !== undefined) merged.legendTitle = settings.legendTitle;
  return merged as AdvancedPlotSettings;
}

export function savedStyles(): Record<string, AdvancedPlotSettings> {
  try {
    const parsed = JSON.parse(read(SAVED_KEY) || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export function savedStyleNames(): string[] {
  return Object.keys(savedStyles()).slice(0, 20);
}

/** The look a plot without settings of its own starts from. */
function template(): { style: AdvancedPlotSettings; stamp: number } | undefined {
  try {
    const parsed = JSON.parse(read(TEMPLATE_KEY) || "null");
    return parsed && typeof parsed === "object" && parsed.style && typeof parsed.stamp === "number" ? parsed : undefined;
  } catch {
    return undefined;
  }
}

export function styleTemplate(): AdvancedPlotSettings | undefined {
  return template()?.style;
}

/**
 * Register a page's plot settings (App, QC, completeness) so styles can reach
 * them. A page that was closed when a style was applied to all plots catches
 * up when it opens.
 */
export function registerStyleStore(id: string, store: Store): () => void {
  stores.set(id, store);
  const current = template();
  const seenKey = `copylot:plotStyleSeen.${id}`;
  if (current && Number(read(seenKey) || 0) < current.stamp) {
    store.setAll(current.style);
    write(seenKey, String(current.stamp));
  }
  return () => { if (stores.get(id) === store) stores.delete(id); };
}

function activeSettings(): AdvancedPlotSettings | null {
  for (const store of stores.values()) {
    const settings = store.active();
    if (settings) return settings;
  }
  return null;
}

export function saveStyle(name: string): string {
  const clean = name.trim().slice(0, 40);
  if (!clean) throw new Error("Name the style to save it.");
  const settings = activeSettings();
  if (!settings) throw new Error("Open a plot first; its look is what gets saved.");
  write(SAVED_KEY, JSON.stringify({ ...savedStyles(), [clean]: styleOf(settings) }));
  window.dispatchEvent(new Event(CHANGED));
  return `Saved this plot's look as the style "${clean}".`;
}

export function applyStyle(name: string, scope: "this" | "all"): string {
  const style = name ? savedStyles()[name] : (() => {
    const settings = activeSettings();
    return settings ? styleOf(settings) : undefined;
  })();
  if (!style) throw new Error(name ? `There is no saved style called "${name}".` : "Open a plot first.");
  if (scope === "this") {
    const store = [...stores.values()].find(candidate => candidate.active());
    if (!store) throw new Error("Open a plot first.");
    store.setActive(withStyle(store.active() ?? {}, style));
    return name ? `Applied the style "${name}" to this plot.` : "This plot already has this look.";
  }
  let count = 0;
  const stamp = Date.now();
  for (const [id, store] of stores) {
    count += store.setAll(style);
    write(`copylot:plotStyleSeen.${id}`, String(stamp));
  }
  write(TEMPLATE_KEY, JSON.stringify({ style, stamp }));
  window.dispatchEvent(new Event(CHANGED));
  return `Applied ${name ? `the style "${name}"` : "this look"} to ${count} plot${count === 1 ? "" : "s"} with settings, `
    + "and every plot you open next starts from it. Titles and axis texts were kept.";
}
