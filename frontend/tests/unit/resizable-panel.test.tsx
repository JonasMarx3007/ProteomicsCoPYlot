/**
 * Side panels (navigation, chatbot, protein lists) can be dragged wider or narrower; the width
 * is remembered per panel and the handle also takes the keyboard (2026-10-14).
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { PANEL_WIDTH_LIMITS, resizeHandleClass, useResizablePanel } from "../../src/lib/useResizablePanel";

function Panel({ edge }: { edge: "left" | "right" }) {
  const panel = useResizablePanel("test.panel", 300, "test panel");
  return (
    <aside style={{ width: `${panel.width}px` }} data-testid="panel">
      <div data-testid="handle" className={resizeHandleClass(edge)} {...panel.handleProps(edge)} />
    </aside>
  );
}

describe("useResizablePanel", () => {
  beforeEach(() => window.localStorage.clear());

  it("starts at the default width and grows when its right-edge handle is dragged right", () => {
    render(<Panel edge="right" />);
    const handle = screen.getByTestId("handle");
    expect(screen.getByTestId("panel").style.width).toBe("300px");
    expect(handle.getAttribute("role")).toBe("separator");
    act(() => { fireEvent.pointerDown(handle, { button: 0, clientX: 100, pointerId: 1 }); });
    act(() => { fireEvent.pointerMove(handle, { clientX: 160, pointerId: 1 }); });
    act(() => { fireEvent.pointerUp(handle, { clientX: 160, pointerId: 1 }); });
    expect(screen.getByTestId("panel").style.width).toBe("360px");
    expect(window.localStorage.getItem("test.panel")).toBe("360");
  });

  it("a left-edge handle grows the panel when dragged left and respects the limits", () => {
    render(<Panel edge="left" />);
    const handle = screen.getByTestId("handle");
    act(() => { fireEvent.pointerDown(handle, { button: 0, clientX: 500, pointerId: 1 }); });
    act(() => { fireEvent.pointerMove(handle, { clientX: 450, pointerId: 1 }); });
    expect(screen.getByTestId("panel").style.width).toBe("350px");
    act(() => { fireEvent.pointerMove(handle, { clientX: -5000, pointerId: 1 }); });
    expect(screen.getByTestId("panel").style.width).toBe(`${PANEL_WIDTH_LIMITS.max}px`);
    act(() => { fireEvent.pointerMove(handle, { clientX: 5000, pointerId: 1 }); });
    expect(screen.getByTestId("panel").style.width).toBe(`${PANEL_WIDTH_LIMITS.min}px`);
    act(() => { fireEvent.pointerUp(handle, { pointerId: 1 }); });
  });

  it("remembers the width, takes the arrow keys and resets on a double click", () => {
    window.localStorage.setItem("test.panel", "400");
    render(<Panel edge="right" />);
    const handle = screen.getByTestId("handle");
    expect(screen.getByTestId("panel").style.width).toBe("400px");
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(screen.getByTestId("panel").style.width).toBe("416px");
    fireEvent.keyDown(handle, { key: "ArrowLeft", shiftKey: true });
    expect(screen.getByTestId("panel").style.width).toBe("368px");
    fireEvent.doubleClick(handle);
    expect(screen.getByTestId("panel").style.width).toBe("300px");
    expect(window.localStorage.getItem("test.panel")).toBeNull();
  });

  it("ends a drag on unmount and restores text selection", () => {
    const previous = document.body.style.userSelect;
    const { unmount } = render(<Panel edge="right" />);
    fireEvent.pointerDown(screen.getByTestId("handle"), { button: 0, clientX: 100, pointerId: 1 });
    expect(document.body.style.userSelect).toBe("none");
    unmount();
    expect(document.body.style.userSelect).toBe(previous);
    fireEvent.pointerMove(window, { clientX: 200, pointerId: 1 });
    expect(window.localStorage.getItem("test.panel")).toBeNull();
  });
});
