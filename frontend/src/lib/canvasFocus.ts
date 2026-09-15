import { useLayoutEffect } from "react";

export type CanvasFocus = { kind: "protein" | "phospho" | "phosprot"; features: string[]; conditions: string[]; allSites: boolean };
let applyFocus: ((focus: CanvasFocus) => string) | undefined;

export function useCanvasFocus(handler: (focus: CanvasFocus) => string) {
  useLayoutEffect(() => {
    applyFocus = handler;
    return () => { if (applyFocus === handler) applyFocus = undefined; };
  }, [handler]);
}

export function focusCanvas(value: unknown): string {
  if (!applyFocus || typeof value !== "string") throw new Error("Open the canvas before focusing a feature.");
  const focus = JSON.parse(value) as CanvasFocus;
  if (!focus || !["protein", "phospho", "phosprot"].includes(focus.kind) ||
      !Array.isArray(focus.features) || !focus.features.length || focus.features.length > 20 ||
      !focus.features.every(item => typeof item === "string" && item.trim()) ||
      !Array.isArray(focus.conditions) || focus.conditions.length !== 2 ||
      !focus.conditions.every(item => typeof item === "string" && item.trim()) ||
      new Set(focus.conditions).size !== 2 || typeof focus.allSites !== "boolean" ||
      (focus.features.length > 1 && !focus.allSites) || (focus.allSites && focus.kind !== "phospho")) {
    throw new Error("The resolved canvas feature scope is invalid.");
  }
  return applyFocus(focus);
}
