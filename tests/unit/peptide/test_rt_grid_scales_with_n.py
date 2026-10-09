"""The RT hexbin/density grid follows the data: `Bins` is a ceiling.

1 000 cells across 60 points drew a white figure; the grid is held to about
two cells per root-n point, and the colour bar says what it counts.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services import peptide_tools


@pytest.mark.parametrize("rows,method,expected", [(60, "Hexbin Plot", 15), (60, "Density Plot", 15), (50_000, "Hexbin Plot", 447), (50_000, "Density Plot", 447)])
def test_the_grid_is_capped_by_the_row_count(monkeypatch, rows, method, expected):
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 120, rows)
    monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: pd.DataFrame({"Predicted.RT": x, "RT": x + rng.normal(0, 2, rows)}))
    captured = {}

    def capture(fig, plt, **kwargs):
        ax = fig.axes[0]
        captured["colorbar"] = fig.axes[1].get_ylabel()
        if method == "Hexbin Plot":
            captured["cells"] = len(ax.collections[0].get_offsets())
        else:  # hist2d draws a QuadMesh of grid x grid cells
            captured["cells"] = int(round(ax.collections[0].get_array().size ** 0.5))
        plt.close(fig)
        return b"png"
    monkeypatch.setattr(peptide_tools, "_to_png_bytes", capture)
    render = getattr(peptide_tools.peptide_rt_plot, "__wrapped__", peptide_tools.peptide_rt_plot)
    render(method=method, bins=1000, dpi=72)
    assert captured["colorbar"] == "Observations per bin"
    if method == "Density Plot":
        assert captured["cells"] == expected
    else:
        # hexbin draws roughly gridsize x gridsize hexagons; well below 1000 x 1000.
        assert captured["cells"] <= (expected + 1) * (expected + 1) * 2
        assert captured["cells"] > 50


def test_an_explicit_smaller_bins_value_still_wins(monkeypatch):
    rng = np.random.default_rng(1)
    x = rng.uniform(0, 120, 50_000)
    monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: pd.DataFrame({"Predicted.RT": x, "RT": x}))
    captured = {}

    def capture(fig, plt, **kwargs):
        captured["cells"] = int(round(fig.axes[0].collections[0].get_array().size ** 0.5))
        plt.close(fig)
        return b"png"
    monkeypatch.setattr(peptide_tools, "_to_png_bytes", capture)
    render = getattr(peptide_tools.peptide_rt_plot, "__wrapped__", peptide_tools.peptide_rt_plot)
    render(method="Density Plot", bins=40, dpi=72)
    assert captured["cells"] == 40
