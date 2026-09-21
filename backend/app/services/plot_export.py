from __future__ import annotations

import io
import math
from contextvars import ContextVar
from threading import RLock

plot_output_format: ContextVar[str] = ContextVar("plot_output_format", default="png")
# Formats matplotlib writes as vectors rather than pixels.
_VECTOR_FORMATS = frozenset({"pdf", "svg"})
_SAVE_LOCK = RLock()


class PlotBytes(bytes):
    """Image payload with a notice kept outside the exported artwork."""

    def __new__(cls, content: bytes, notice: str = ""):
        result = super().__new__(cls, content)
        result.notice = notice
        return result

# Upper bounds for a figure that is allowed to grow past the requested size.
# They mirror MAX_PLOT_WIDTH_CM / MAX_PLOT_HEIGHT_CM / MAX_PLOT_PIXELS in
# plot_limits, so an auto-grown canvas can never end up larger than a canvas the
# user is allowed to ask for. Duplicated rather than imported because
# plot_limits pulls in Starlette and this module is used off the HTTP path too.
MAX_AUTO_FIT_CM = 60.0
MAX_AUTO_FIT_PIXELS = 24_000_000
# Breathing room added around the measured label extent, in inches.
AUTO_FIT_MARGIN_INCHES = 0.12


def fit_figure_to_labels(
    fig,
    plt,
    *,
    dpi: int = 150,
    max_width_cm: float = MAX_AUTO_FIT_CM,
    max_height_cm: float = MAX_AUTO_FIT_CM,
    margin_inches: float = AUTO_FIT_MARGIN_INCHES,
    max_passes: int = 3,
    max_pixels: int = MAX_AUTO_FIT_PIXELS,
) -> tuple[float, float]:
    """Treat the requested figure size as a floor and grow it until labels fit.

    ``to_png_bytes`` refuses to render a figure whose tight bounding box spills
    off the canvas, because silently shrinking or cropping a scientific figure
    is worse than an error. For label-heavy plots (a GO term with forty gene
    names down the side) the requested size is simply too small, and the honest
    fix is a bigger canvas rather than a smaller error. Measure what the labels
    actually need, enlarge to that, and re-measure a couple of times because
    ``tight_layout`` redistributes the extra room. The figure is never shrunk,
    the caller's DPI is untouched, and growth stops at the same physical and
    pixel ceilings the HTTP layer enforces - so ``to_png_bytes`` still raises
    for a figure that does not fit even at the maximum size.

    Returns the final figure size in inches.
    """
    resolved_dpi = max(72, int(dpi))
    tolerance = 1.0 / resolved_dpi
    max_width_in = cm_to_inch(max_width_cm)
    max_height_in = cm_to_inch(max_height_cm)
    pixel_budget = max(1, int(max_pixels))
    width, height = (float(value) for value in fig.get_size_inches())

    with _SAVE_LOCK, plt.rc_context({"savefig.bbox": None}):
        for _ in range(max(1, int(max_passes))):
            fig.tight_layout(pad=0.8)
            fig.canvas.draw()
            bounds = fig.get_tightbbox(fig.canvas.get_renderer())
            if bounds is None:
                break
            width, height = (float(value) for value in fig.get_size_inches())
            overflow_x = max(0.0, -bounds.x0) + max(0.0, bounds.x1 - width)
            overflow_y = max(0.0, -bounds.y0) + max(0.0, bounds.y1 - height)
            if overflow_x <= tolerance and overflow_y <= tolerance:
                break
            target_width = width + (overflow_x + margin_inches if overflow_x > tolerance else 0.0)
            target_height = height + (overflow_y + margin_inches if overflow_y > tolerance else 0.0)
            target_width = min(target_width, max_width_in)
            target_height = min(target_height, max_height_in)
            # A tall canvas at 600 dpi can blow past the pixel budget long
            # before it reaches the physical ceiling; scale the growth back
            # rather than handing the browser a figure it cannot decode.
            pixels = (target_width * resolved_dpi) * (target_height * resolved_dpi)
            if pixels > pixel_budget:
                shrink = math.sqrt(pixel_budget / pixels)
                target_width = max(width, target_width * shrink)
                target_height = max(height, target_height * shrink)
            if target_width <= width + tolerance and target_height <= height + tolerance:
                break
            fig.set_size_inches(max(width, target_width), max(height, target_height))
            width, height = (float(value) for value in fig.get_size_inches())

        # Growing the canvas does not always close the gap: tight_layout gives
        # the extra room straight back to the axes, so a long y label can still
        # sit a hundredth of an inch outside after several passes, and the guard
        # in `to_png_bytes` refuses it. What is left is absorbed by pulling the
        # axes in, which removes the overflow by construction rather than by
        # hoping the next pass converges.
        for _ in range(2):
            fig.canvas.draw()
            bounds = fig.get_tightbbox(fig.canvas.get_renderer())
            if bounds is None:
                break
            width, height = (float(value) for value in fig.get_size_inches())
            left = max(0.0, -bounds.x0)
            right = max(0.0, bounds.x1 - width)
            bottom = max(0.0, -bounds.y0)
            top = max(0.0, bounds.y1 - height)
            if max(left, right, bottom, top) <= tolerance:
                break
            pad = margin_inches * 0.5
            box = fig.subplotpars
            new_left = box.left + (left + pad) / width
            new_right = box.right - (right + pad) / width
            new_bottom = box.bottom + (bottom + pad) / height
            new_top = box.top - (top + pad) / height
            # An impossible layout -- labels wider than any canvas -- would ask
            # for margins that leave no axes at all. Leave it alone rather than
            # raising here: the guard in `to_png_bytes` is the place that says
            # a figure does not fit, and it says so with a message the user can
            # act on.
            if new_right - new_left < 0.2 or new_top - new_bottom < 0.2:
                break
            fig.subplots_adjust(
                left=new_left, right=new_right, bottom=new_bottom, top=new_top
            )
        # The layout measured here is the one that must be rendered, so the
        # serializer must not run tight_layout over it again.
        fig._copylot_layout_final = True

    return width, height


def to_png_bytes(fig, plt, dpi: int = 150, tight: bool = True) -> bytes:
    """Serialize the request's image format; tight fits layout, never crops the canvas."""
    buf = io.BytesIO()
    fmt = plot_output_format.get()
    save_kwargs = {"format": fmt, "dpi": max(72, int(dpi))}
    if getattr(fig, "_copylot_transparent_background", False):
        save_kwargs["transparent"] = True
    try:
        if fmt in _VECTOR_FORMATS:
            # A rasterized artist would drop a bitmap into a vector file, which
            # defeats the reason for asking for one.
            for artist in fig.findobj():
                if artist.get_rasterized():
                    artist.set_rasterized(False)
        with _SAVE_LOCK, plt.rc_context({"pdf.fonttype": 42, "savefig.bbox": None}):
            fig.canvas.draw()
            if tight and not getattr(fig, "_copylot_layout_final", False):
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
    notice = getattr(fig, "_copylot_notice", "")
    return PlotBytes(buf.getvalue(), notice) if notice else buf.getvalue()


def cm_to_inch(value_cm: float) -> float:
    value = float(value_cm)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Figure dimensions must be finite and greater than zero.")
    return value / 2.54


def cm_to_px(value_cm: float) -> int:
    return max(320, int(round((cm_to_inch(value_cm) * 96.0))))
