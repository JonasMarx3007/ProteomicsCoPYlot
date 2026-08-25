from __future__ import annotations

import inspect
import math
from dataclasses import dataclass

from starlette.requests import Request
from starlette.routing import Match


MIN_PLOT_WIDTH_CM = 1.0
MAX_PLOT_WIDTH_CM = 60.0
MIN_PLOT_HEIGHT_CM = 1.0
MAX_PLOT_HEIGHT_CM = 60.0
MIN_PLOT_DPI = 72
MAX_PLOT_DPI = 600
MAX_PLOT_PIXELS = 24_000_000
HTML_LAYOUT_DPI = 96


class PlotSizeValidationError(ValueError):
    pass


@dataclass(frozen=True)
class PlotRenderSize:
    width_cm: float
    height_cm: float
    dpi: int
    width_px: int
    height_px: int

    @property
    def pixels(self) -> int:
        return self.width_px * self.height_px


def validate_plot_size(width_cm: float, height_cm: float, dpi: int) -> PlotRenderSize:
    try:
        width = float(width_cm)
        height = float(height_cm)
        dpi_value = float(dpi)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PlotSizeValidationError(
            "Plot width, height, and DPI must be finite numbers."
        ) from exc

    if not math.isfinite(width) or not math.isfinite(height) or not math.isfinite(dpi_value):
        raise PlotSizeValidationError("Plot width, height, and DPI must be finite numbers.")
    if not dpi_value.is_integer():
        raise PlotSizeValidationError("Plot DPI must be a whole number.")
    resolved_dpi = int(dpi_value)
    if width < MIN_PLOT_WIDTH_CM or width > MAX_PLOT_WIDTH_CM:
        raise PlotSizeValidationError(
            f"Plot width must be between {MIN_PLOT_WIDTH_CM:g} and {MAX_PLOT_WIDTH_CM:g} cm."
        )
    if height < MIN_PLOT_HEIGHT_CM or height > MAX_PLOT_HEIGHT_CM:
        raise PlotSizeValidationError(
            f"Plot height must be between {MIN_PLOT_HEIGHT_CM:g} and {MAX_PLOT_HEIGHT_CM:g} cm."
        )
    if resolved_dpi < MIN_PLOT_DPI or resolved_dpi > MAX_PLOT_DPI:
        raise PlotSizeValidationError(
            f"Plot DPI must be between {MIN_PLOT_DPI} and {MAX_PLOT_DPI}."
        )

    width_px = int(math.ceil(width / 2.54 * resolved_dpi))
    height_px = int(math.ceil(height / 2.54 * resolved_dpi))
    size = PlotRenderSize(width, height, resolved_dpi, width_px, height_px)
    if size.pixels > MAX_PLOT_PIXELS:
        raise PlotSizeValidationError(
            "Requested plot is too large: "
            f"{width_px:,} x {height_px:,} pixels ({size.pixels / 1_000_000:.1f} MP). "
            f"Reduce width, height, or DPI to stay at or below {MAX_PLOT_PIXELS / 1_000_000:.0f} MP."
        )
    return size


def _matched_endpoint_defaults(request: Request) -> dict[str, object]:
    for route in request.app.router.routes:
        try:
            match, _ = route.matches(request.scope)
        except Exception:
            continue
        if match is not Match.FULL:
            continue
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            return {}
        return {
            name: parameter.default
            for name, parameter in inspect.signature(endpoint).parameters.items()
            if parameter.default is not inspect.Parameter.empty
        }
    return {}


def _query_number(request: Request, name: str, default: object) -> float | None:
    raw = request.query_params.get(name)
    if raw is None:
        if default is inspect.Parameter.empty or default is None:
            return None
        raw = default
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PlotSizeValidationError(f"{name} must be a finite number.") from exc
    if not math.isfinite(value):
        raise PlotSizeValidationError(f"{name} must be a finite number.")
    return value


def validate_plot_request(request: Request) -> PlotRenderSize | None:
    """Validate every HTTP plot request before workload admission.

    Endpoint signature defaults are used for omitted query parameters, avoiding
    partial-query bypasses such as a large width/DPI combined with a route's
    taller default height. Interactive HTML layouts use their 96 px/in CSS
    equivalent when the endpoint has no DPI parameter.
    """
    if request.method.upper() != "GET":
        return None
    path = request.url.path
    if not (path.startswith("/api/plots/") or path.startswith("/api/analysis/")):
        return None

    defaults = _matched_endpoint_defaults(request)
    has_dimensions = any(
        name in request.query_params or name in defaults
        for name in ("widthCm", "heightCm", "dpi")
    )
    if not has_dimensions:
        return None

    width = _query_number(request, "widthCm", defaults.get("widthCm", 20.0))
    height = _query_number(request, "heightCm", defaults.get("heightCm", 12.0))
    dpi_default = defaults.get("dpi", HTML_LAYOUT_DPI)
    dpi = _query_number(request, "dpi", dpi_default)
    if width is None or height is None or dpi is None:
        return None
    if not float(dpi).is_integer():
        raise PlotSizeValidationError("dpi must be a whole number.")
    return validate_plot_size(width, height, int(dpi))
