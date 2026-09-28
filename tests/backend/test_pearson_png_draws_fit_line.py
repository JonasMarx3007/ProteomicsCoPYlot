"""The static Pearson PNG draws the same least-squares line as its interactive twin.

The interactive figure, the pip package and the R script all draw it; the
PNG -- the figure the report carries -- plotted the points and stopped.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from app.services import comparison_tools  # noqa: E402


@pytest.fixture
def figures(monkeypatch):
    rng = np.random.default_rng(3)
    x = rng.normal(20, 2, 40)
    y = 0.8 * x + 3 + rng.normal(0, 0.5, 40)
    monkeypatch.setattr(comparison_tools, "_pearson_vectors", lambda **kw: (x, y, "S1", "S2"))
    captured = []
    monkeypatch.setattr(comparison_tools, "_to_png_bytes", lambda fig, plt, **kw: captured.append(fig) or b"")
    return captured, x, y


def _fit_lines(ax):
    return [line for line in ax.get_lines() if len(line.get_xdata()) == 2]


def test_the_png_draws_the_least_squares_line(figures):
    captured, x, y = figures
    comparison_tools.pearson_correlation_png(kind="protein", sample1="S1", sample2="S2")
    lines = _fit_lines(captured[-1].axes[0])
    assert len(lines) == 1
    slope, intercept = np.polyfit(x, y, 1)
    xs, ys = lines[0].get_xdata(), lines[0].get_ydata()
    assert list(xs) == [pytest.approx(x.min()), pytest.approx(x.max())]
    assert ys[0] == pytest.approx(slope * x.min() + intercept)
    assert ys[1] == pytest.approx(slope * x.max() + intercept)


def test_the_reference_line_setting_switches_it_off(figures):
    captured, _, _ = figures
    comparison_tools.pearson_correlation_png(kind="protein", sample1="S1", sample2="S2", advanced={"referenceLineVisible": False})
    assert _fit_lines(captured[-1].axes[0]) == []


def test_the_setting_also_styles_it(figures):
    captured, _, _ = figures
    comparison_tools.pearson_correlation_png(kind="protein", sample1="S1", sample2="S2", advanced={"referenceLineColor": "#ff0000"})
    line = _fit_lines(captured[-1].axes[0])[0]
    assert line.get_color().lower() == "#ff0000"
