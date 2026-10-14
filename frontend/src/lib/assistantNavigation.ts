/** Focus the actual figure after navigation, including lazy pages and image loads. */
export function focusNavigatedPlot(): () => void {
  const stop = () => {
    window.clearInterval(poll);
    window.clearTimeout(deadline);
    window.removeEventListener("wheel", stop);
    window.removeEventListener("touchstart", stop);
    window.removeEventListener("pointerdown", stop);
  };
  const focus = () => {
    const plot = [...document.querySelectorAll<HTMLElement>("main img, main iframe, main svg")].find(element => {
      const box = element.getBoundingClientRect();
      return box.width > 160 && box.height > 100 && !element.closest("[hidden], [inert], [aria-hidden=true]")
        && (!(element instanceof HTMLImageElement) || (element.complete && element.naturalWidth > 0));
    });
    if (plot) {
      plot.scrollIntoView({ block: "start", behavior: "instant" });
      stop();
    }
  };
  const poll = window.setInterval(focus, 100);
  const deadline = window.setTimeout(stop, 20000);
  // Do not pull the user back after they start interacting with the new page.
  window.addEventListener("wheel", stop, { passive: true });
  window.addEventListener("touchstart", stop, { passive: true });
  window.addEventListener("pointerdown", stop, { passive: true });
  return stop;
}
