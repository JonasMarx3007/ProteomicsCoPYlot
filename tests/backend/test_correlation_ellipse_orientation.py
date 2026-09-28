"""A positive correlation ellipse must rise from lower-left to upper-right.

The ellipse view inverts its y axis so that rows read top-down like the matrix
view. A +45 degree patch on an inverted axis renders as "\\", the tilt every
corrplot-style figure uses for a *negative* correlation. The angle is therefore
flipped in data space; this test checks the result in display space, where the
reader sees it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import plot_images


def _render(monkeypatch, r_sign: float):
    rng = np.random.default_rng(1)
    base = rng.normal(20, 1, 200)
    frame = pd.DataFrame({
        "s1": base,
        "s2": base * r_sign + rng.normal(0, 0.05, 200),
        "s3": rng.normal(20, 1, 200),
    })
    metadata = pd.DataFrame({"sample": ["s1", "s2", "s3"], "condition": ["A", "A", "B"]})
    monkeypatch.setattr(plot_images, "log2_qc_frame", lambda kind: frame.copy())
    monkeypatch.setattr(plot_images, "_get_sample_columns", lambda kind, f: ["s1", "s2", "s3"])
    monkeypatch.setattr(plot_images, "_metadata_for_kind", lambda kind, f, c: metadata.copy())
    captured = {}

    def capture(fig, plt, **kwargs):
        captured["fig"] = fig
        return b"\x89PNG\r\n\x1a\n"

    monkeypatch.setattr(plot_images, "_to_png_bytes", capture)
    plot_images.qc_correlation_plot("protein", method="Ellipse", width_cm=6, height_cm=6, dpi=40)
    return captured["fig"]


def _display_slope(fig, ellipse):
    """Direction of the ellipse's long axis in display (pixel) space."""
    ax = ellipse.axes
    cx, cy = ellipse.center
    theta = np.deg2rad(ellipse.angle)
    half = ellipse.width / 2  # width is the long axis: height = 0.9 * (1 - |r|)
    tip = (cx + half * np.cos(theta), cy + half * np.sin(theta))
    p0 = ax.transData.transform((cx, cy))
    p1 = ax.transData.transform(tip)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    return dx, dy


def _off_diagonal_ellipse(fig):
    from matplotlib.patches import Ellipse

    ax = fig.axes[0]
    # (row 0, column 1) or (row 1, column 0): s1 vs s2, the correlated pair.
    for patch in ax.patches:
        if isinstance(patch, Ellipse) and abs(patch.center[0] - patch.center[1]) > 0.5 and patch.height < 0.3:
            return patch
    raise AssertionError("no strongly correlated off-diagonal ellipse found")


def test_positive_correlation_rises_to_the_right(monkeypatch) -> None:
    fig = _render(monkeypatch, +1.0)
    dx, dy = _display_slope(fig, _off_diagonal_ellipse(fig))
    # Display y grows upwards: a "/" tilt has dx and dy of the same sign.
    assert dx * dy > 0, f"positive r drawn as '\\\\' (dx={dx:.1f}, dy={dy:.1f})"


def test_negative_correlation_falls_to_the_right(monkeypatch) -> None:
    fig = _render(monkeypatch, -1.0)
    dx, dy = _display_slope(fig, _off_diagonal_ellipse(fig))
    assert dx * dy < 0, f"negative r drawn as '/' (dx={dx:.1f}, dy={dy:.1f})"


def test_correlation_figure_says_what_it_shows(monkeypatch) -> None:
    fig = _render(monkeypatch, +1.0)
    ax = fig.axes[0]
    assert "Pearson r" in ax.get_title()
    labels = [a.get_ylabel() for a in fig.axes[1:]] + [a.get_xlabel() for a in fig.axes[1:]]
    assert any("Pearson r" in label for label in labels), "colour bar has no label"
