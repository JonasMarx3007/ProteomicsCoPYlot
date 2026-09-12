from __future__ import annotations

import io
import math
from contextvars import ContextVar
from threading import RLock

plot_output_format: ContextVar[str] = ContextVar("plot_output_format", default="png")
_SAVE_LOCK = RLock()


def to_png_bytes(fig, plt, dpi: int = 150, tight: bool = True) -> bytes:
    """Serialize the request's image format; tight fits layout, never crops the canvas."""
    buf = io.BytesIO()
    fmt = plot_output_format.get()
    save_kwargs = {"format": fmt, "dpi": max(72, int(dpi))}
    if getattr(fig, "_copylot_transparent_background", False):
        save_kwargs["transparent"] = True
    try:
        if fmt == "pdf":
            for artist in fig.findobj():
                if artist.get_rasterized():
                    artist.set_rasterized(False)
        with _SAVE_LOCK, plt.rc_context({"pdf.fonttype": 42, "savefig.bbox": None}):
            fig.canvas.draw()
            if tight:
                fig.tight_layout(pad=0.8)
            fig.canvas.draw()
            bounds = fig.get_tightbbox(fig.canvas.get_renderer())
            width, height = fig.get_size_inches()
            tolerance = 1 / save_kwargs["dpi"]
            if bounds is not None and (
                bounds.x0 < -tolerance or bounds.y0 < -tolerance
                or bounds.x1 > width + tolerance or bounds.y1 > height + tolerance
            ):
                raise ValueError(
                    "Plot labels do not fit the selected figure size. "
                    "Increase width/height or reduce text size."
                )
            fig.savefig(buf, **save_kwargs)
    finally:
        plt.close(fig)
    return buf.getvalue()


def cm_to_inch(value_cm: float) -> float:
    value = float(value_cm)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Figure dimensions must be finite and greater than zero.")
    return value / 2.54


def cm_to_px(value_cm: float) -> int:
    return max(320, int(round((cm_to_inch(value_cm) * 96.0))))
