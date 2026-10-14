import { afterEach, expect, it, vi } from "vitest";
import { focusNavigatedPlot } from "../../src/lib/assistantNavigation";

afterEach(() => { vi.useRealTimers(); document.body.replaceChildren(); });

function plot() {
  const main = document.createElement("main");
  const frame = document.createElement("iframe");
  frame.getBoundingClientRect = () => ({ width: 640, height: 480 }) as DOMRect;
  frame.scrollIntoView = vi.fn();
  main.append(frame);
  document.body.append(main);
  return frame;
}

it("waits for lazy plots and scrolls only once", () => {
  vi.useFakeTimers();
  const stop = focusNavigatedPlot();
  vi.advanceTimersByTime(500);
  const frame = plot();
  vi.advanceTimersByTime(100);
  expect(frame.scrollIntoView).toHaveBeenCalledWith({ block: "start", behavior: "instant" });
  vi.advanceTimersByTime(1000);
  expect(frame.scrollIntoView).toHaveBeenCalledTimes(1);
  stop();
});

it.each(["wheel", "touchstart", "pointerdown"])("respects user interaction: %s", event => {
  vi.useFakeTimers();
  const stop = focusNavigatedPlot();
  window.dispatchEvent(new Event(event));
  const frame = plot();
  vi.advanceTimersByTime(1000);
  expect(frame.scrollIntoView).not.toHaveBeenCalled();
  stop();
});

it("ignores hidden content and stops after leaving or timing out", () => {
  vi.useFakeTimers();
  const frame = plot();
  frame.hidden = true;
  const stop = focusNavigatedPlot();
  vi.advanceTimersByTime(20100);
  frame.hidden = false;
  vi.advanceTimersByTime(100);
  expect(frame.scrollIntoView).not.toHaveBeenCalled();
  stop();
  const cancel = focusNavigatedPlot();
  cancel();
  vi.advanceTimersByTime(100);
  expect(frame.scrollIntoView).not.toHaveBeenCalled();
});
