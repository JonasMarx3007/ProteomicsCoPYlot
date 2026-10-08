// The rendered plot as an image, for Advanced assistant models that read
// images. Plots are server-rendered <img> elements or Plotly figures in a
// same-origin frame; whichever is largest on screen is captured, scaled to at
// most 1024 px wide. Nothing is stored; a capture that fails sends no image.
const MAX_WIDTH = 1024;
const MAX_CHARS = 2_900_000;

function visibleArea(element: Element): number {
  const box = element.getBoundingClientRect();
  return box.width > 0 && box.height > 0 ? box.width * box.height : 0;
}

function encode(source: CanvasImageSource, width: number, height: number): string | undefined {
  const scale = Math.min(1, MAX_WIDTH / Math.max(1, width));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  const context = canvas.getContext("2d");
  if (!context) return undefined;
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(source, 0, 0, canvas.width, canvas.height);
  try {
    const png = canvas.toDataURL("image/png");
    if (png.length <= MAX_CHARS) return png;
    const jpeg = canvas.toDataURL("image/jpeg", 0.85);
    return jpeg.length <= MAX_CHARS ? jpeg : undefined;
  } catch {
    return undefined; // a cross-origin image taints the canvas
  }
}

type PlotlyWindow = Window & { Plotly?: { toImage: (figure: Element, options: object) => Promise<string> } };

export async function capturePlotImage(root: ParentNode = document): Promise<string | undefined> {
  const images = [...root.querySelectorAll<HTMLImageElement>("main img")]
    .filter(image => image.complete && image.naturalWidth > 0 && visibleArea(image) > 0)
    .sort((a, b) => visibleArea(b) - visibleArea(a));
  const frames = [...root.querySelectorAll<HTMLIFrameElement>("main iframe")]
    .filter(frame => visibleArea(frame) > 0)
    .sort((a, b) => visibleArea(b) - visibleArea(a));
  const image = images[0];
  const frame = frames[0];
  if (frame && (!image || visibleArea(frame) > visibleArea(image))) {
    try {
      const view = frame.contentWindow as PlotlyWindow | null;
      const figure = frame.contentDocument?.querySelector(".js-plotly-plot");
      if (view?.Plotly && figure) {
        const url = await view.Plotly.toImage(figure, { format: "png", width: 900, height: 600 });
        if (/^data:image\/png;base64,/.test(url) && url.length <= MAX_CHARS) return url;
      }
    } catch {
      // fall through to the image, if any
    }
  }
  return image ? encode(image, image.naturalWidth, image.naturalHeight) : undefined;
}
