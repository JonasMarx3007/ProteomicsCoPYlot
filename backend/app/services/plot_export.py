from __future__ import annotations

import io
import math
from contextvars import ContextVar
from threading import RLock

plot_output_format: ContextVar[str] = ContextVar("plot_output_format", default="png")
# False while a request asks for a download in another format: that render is a
# file to save, not the figure on screen, so it gets no notebook export of its own.
notebook_capture_allowed: ContextVar[bool] = ContextVar("notebook_capture_allowed", default=True)
# Why this render offers no notebook export. The request middleware puts a
# fresh dict here; the route runs in a worker thread with a copy of the context,
# so the reason is written into the shared dict rather than set on the variable.
notebook_unavailable: ContextVar[dict | None] = ContextVar("notebook_unavailable", default=None)


def note_notebook_unavailable(reason) -> None:
    """Say, under the plot, why it has no notebook export (GUI only)."""
    holder = notebook_unavailable.get()
    text = str(reason).strip()
    if holder is not None and text and "reason" not in holder:
        holder["reason"] = text
# Formats matplotlib writes as vectors rather than pixels.
_VECTOR_FORMATS = frozenset({"pdf", "svg"})
_SAVE_LOCK = RLock()
# One figure is built at a time. The server answers requests on several
# threads, and matplotlib is not thread-safe: its math-text parser (used for
# every tick label) keeps parser state, so two figures laid out at once could
# fail with an internal error ("pop from empty list") or corrupt each other.
# Re-entrant, and the same lock as the save, so a render that saves holds it
# once.
RENDER_LOCK = _SAVE_LOCK


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


def _tick_label_space(fig, renderer) -> tuple[float, float]:
    """Extra inches needed to separate adjacent tick labels, without hiding any."""
    extra = [0.0, 0.0]
    for ax in getattr(fig, "axes", []):
        for dimension, labels in enumerate((ax.get_xticklabels(), ax.get_yticklabels())):
            boxes = [label.get_window_extent(renderer) for label in labels
                     if label.get_visible() and label.get_text()]
            boxes.sort(key=lambda box: box.x0 if dimension == 0 else box.y0)
            ratio = 1.0
            for first, second in zip(boxes, boxes[1:]):
                first_center = (first.x0 + first.x1) / 2 if dimension == 0 else (first.y0 + first.y1) / 2
                second_center = (second.x0 + second.x1) / 2 if dimension == 0 else (second.y0 + second.y1) / 2
                distance = second_center - first_center
                if distance <= 0:
                    continue
                extent = (first.width + second.width) / 2 if dimension == 0 else (first.height + second.height) / 2
                ratio = max(ratio, (extent + fig.dpi * 0.02) / distance)
            span = ax.bbox.width if dimension == 0 else ax.bbox.height
            extra[dimension] = max(extra[dimension], span * (ratio - 1) / fig.dpi)
    return tuple(extra)


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
    """Grow a crowded figure within the physical/pixel limits, preserving DPI.

    Requested dimensions are a minimum. Return the final size in inches.
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
            tick_width, tick_height = _tick_label_space(fig, fig.canvas.get_renderer())
            overflow_x += tick_width
            overflow_y += tick_height
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
                # Preserving an existing dimension can undo the proportional
                # reduction above. Cap the other dimension to the remaining budget.
                target_width = min(target_width, pixel_budget / resolved_dpi**2 / height)
                target_height = min(target_height, pixel_budget / resolved_dpi**2 / target_width)
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
    """Serialize without clipping labels; grow crowded plots within safe limits."""
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
            crowded_ticks = max(_tick_label_space(fig, fig.canvas.get_renderer())) > tolerance
            if crowded_ticks or (bounds is not None and (
                bounds.x0 < -tolerance or bounds.y0 < -tolerance
                or bounds.x1 > width + tolerance or bounds.y1 > height + tolerance
            )):
                fit_figure_to_labels(fig, plt, dpi=save_kwargs["dpi"])
                fig.canvas.draw()
                bounds = fig.get_tightbbox(fig.canvas.get_renderer())
                width, height = fig.get_size_inches()
                if bounds is not None and (
                    bounds.x0 < -tolerance or bounds.y0 < -tolerance
                    or bounds.x1 > width + tolerance or bounds.y1 > height + tolerance
                ):
                    raise ValueError(
                        "Plot labels do not fit even after automatic layout adjustment. "
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
