import type { AdvancedPlotSettings } from "./types";

export function compactTextElement(value: AdvancedPlotSettings["titleElement"]) {
  if (!value) return undefined;
  const text = value.text?.trim();
  const next = {
    ...(text ? { text } : {}),
    ...(value.size && value.size > 0 ? { size: value.size } : {}),
    ...(value.xOffset ? { xOffset: value.xOffset } : {}),
    ...(value.yOffset ? { yOffset: value.yOffset } : {}),
    ...(value.bold ? { bold: true } : {}),
    ...(value.italic ? { italic: true } : {}),
  };
  return Object.keys(next).length ? next : undefined;
}

export function compactMap(value: Record<string, string> | undefined): Record<string, string> | undefined {
  const entries = Object.entries(value ?? {})
    .map(([key, val]) => [key.trim(), val.trim()] as const)
    .filter(([key, val]) => key && val);
  return entries.length ? Object.fromEntries(entries) : undefined;
}
