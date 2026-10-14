import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

/**
 * A side panel the user can widen or narrow by dragging its inner edge
 * (2026-10-14: navigation, chatbot and protein-list panels). The width is
 * remembered per panel in localStorage; the handle also takes the arrow keys
 * and resets to the default on a double click.
 */
export type ResizablePanel = {
  width: number;
  /** Props for the drag handle; `edge` is the side of the panel the handle sits on. */
  handleProps: (edge: "left" | "right") => {
    role: "separator";
    "aria-orientation": "vertical";
    "aria-valuenow": number;
    "aria-valuemin": number;
    "aria-valuemax": number;
    "aria-label": string;
    tabIndex: 0;
    onPointerDown: (event: PointerEvent<HTMLElement>) => void;
    onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
    onDoubleClick: () => void;
    style: { touchAction: "none" };
  };
};

export const PANEL_WIDTH_LIMITS = { min: 256, max: 720 } as const;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

function readStored(key: string, fallback: number): number {
  try {
    const raw = window.localStorage.getItem(key);
    const value = raw === null ? Number.NaN : Number(raw);
    return Number.isFinite(value) ? clamp(value, PANEL_WIDTH_LIMITS.min, PANEL_WIDTH_LIMITS.max) : fallback;
  } catch {
    return fallback;
  }
}

export function useResizablePanel(storageKey: string, defaultWidth: number, label: string): ResizablePanel {
  const [width, setWidth] = useState(() => readStored(storageKey, defaultWidth));
  const stopDrag = useRef<(() => void) | null>(null);
  useEffect(() => () => stopDrag.current?.(), []);

  useEffect(() => {
    try {
      if (width === defaultWidth) window.localStorage.removeItem(storageKey);
      else window.localStorage.setItem(storageKey, String(width));
    } catch {
      // Storage may be unavailable (private window); the width still applies for the session.
    }
  }, [width, storageKey, defaultWidth]);

  const handleProps = useCallback<ResizablePanel["handleProps"]>((edge) => ({
    role: "separator",
    "aria-orientation": "vertical",
    "aria-valuenow": width,
    "aria-valuemin": PANEL_WIDTH_LIMITS.min,
    "aria-valuemax": PANEL_WIDTH_LIMITS.max,
    "aria-label": `Resize ${label}`,
    tabIndex: 0,
    style: { touchAction: "none" },
    onDoubleClick: () => setWidth(defaultWidth),
    onKeyDown: (event) => {
      const step = event.shiftKey ? 48 : 16;
      // The handle on a panel's right edge grows the panel when it moves right; on the left edge, when it moves left.
      const grow = edge === "right" ? 1 : -1;
      if (event.key === "ArrowRight") setWidth((current) => clamp(current + grow * step, PANEL_WIDTH_LIMITS.min, PANEL_WIDTH_LIMITS.max));
      else if (event.key === "ArrowLeft") setWidth((current) => clamp(current - grow * step, PANEL_WIDTH_LIMITS.min, PANEL_WIDTH_LIMITS.max));
      else if (event.key === "Home") setWidth(PANEL_WIDTH_LIMITS.min);
      else if (event.key === "End") setWidth(PANEL_WIDTH_LIMITS.max);
      else return;
      event.preventDefault();
    },
    onPointerDown: (event) => {
      if (event.button !== 0) return;
      stopDrag.current?.();
      event.preventDefault();
      const target = event.currentTarget;
      const startX = event.clientX;
      const startWidth = width;
      const grow = edge === "right" ? 1 : -1;
      const previousCursor = document.body.style.cursor;
      const previousSelect = document.body.style.userSelect;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      try {
        target.setPointerCapture?.(event.pointerId);
      } catch {
        // Capture is a convenience; the window listener below ends the drag either way.
      }
      const move = (moveEvent: globalThis.PointerEvent) => {
        if (moveEvent.pointerId !== event.pointerId) return;
        setWidth(clamp(startWidth + grow * (moveEvent.clientX - startX), PANEL_WIDTH_LIMITS.min, PANEL_WIDTH_LIMITS.max));
      };
      const stop = () => {
        document.body.style.cursor = previousCursor;
        document.body.style.userSelect = previousSelect;
        window.removeEventListener("pointermove", move);
        target.removeEventListener("pointerup", stop);
        target.removeEventListener("pointercancel", stop);
        window.removeEventListener("pointerup", stop);
        window.removeEventListener("pointercancel", stop);
        window.removeEventListener("blur", stop);
        stopDrag.current = null;
      };
      stopDrag.current = stop;
      window.addEventListener("pointermove", move);
      target.addEventListener("pointerup", stop);
      target.addEventListener("pointercancel", stop);
      window.addEventListener("pointerup", stop);
      window.addEventListener("pointercancel", stop);
      window.addEventListener("blur", stop);
    },
  }), [width, defaultWidth, label]);

  return { width, handleProps };
}

/** The handle's class names: a thin strip on the panel's inner edge that widens on hover. */
export function resizeHandleClass(edge: "left" | "right"): string {
  return [
    "absolute inset-y-0 z-50 w-2 cursor-col-resize select-none bg-transparent transition hover:bg-slate-300/70 focus-visible:bg-slate-400/70 focus-visible:outline-none",
    edge === "right" ? "-right-1" : "-left-1",
  ].join(" ");
}
