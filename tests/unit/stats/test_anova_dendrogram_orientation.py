"""The row dendrogram beside an ANOVA heatmap must read in the heatmap's row order.

scipy draws a left-oriented dendrogram with leaf 0 at the bottom, while imshow
draws row 0 at the top. Without an axis flip the tree beside the rows belongs
to them in reverse order, and a reader tracing a branch lands on the wrong
features. This holds the app figure and both Python package figures to the
same orientation; the R heatmap already draws both from the bottom up.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage

ROOT = Path(__file__).resolve().parents[3]

from app.services.stats_tools import _anova_heatmap_figure
from proteomicscopylot import notebook_functions


def _frame(n=12, seed=3):
    rng = np.random.default_rng(seed)
    samples = [f"{c}_{i}" for c in ("A", "B") for i in range(1, 4)]
    values = rng.normal(20, 1, (n, len(samples)))
    values[: n // 2, :3] += 3
    frame = pd.DataFrame(values, columns=samples)
    frame.insert(0, "ProteinNames", [f"P{i:03d}" for i in range(n)])
    frame["adj_pval"] = 0.001
    metadata = pd.DataFrame({"sample": samples, "condition": [s[0] for s in samples]})
    return frame, metadata, samples


def _expected_order(frame, samples):
    matrix = frame[samples].to_numpy(dtype=float)
    z = (matrix - matrix.mean(axis=1, keepdims=True)) / matrix.std(axis=1, ddof=1, keepdims=True)
    return leaves_list(linkage(z, method="average", metric="euclidean"))


def _dendrogram_axis(fig):
    # The dendrogram axes is the only one holding line collections but no image.
    candidates = [ax for ax in fig.axes if ax.collections and not ax.images]
    assert candidates, "no dendrogram axes found"
    return candidates


def _heatmap_axis(fig):
    return next(ax for ax in fig.axes if ax.images and ax.images[0].get_array().ndim == 2
                and ax.images[0].get_array().shape[0] > 1)


def _assert_row_tree_matches_rows(fig, frame, samples):
    heatmap = _heatmap_axis(fig)
    matrix = heatmap.images[0].get_array()
    ordered = _expected_order(frame, samples)
    z = frame[samples].to_numpy(dtype=float)
    z = (z - z.mean(axis=1, keepdims=True)) / z.std(axis=1, ddof=1, keepdims=True)
    # Samples may be clustered too, so compare rows independent of column order.
    assert np.allclose(np.sort(np.asarray(matrix), axis=1), np.sort(z[ordered], axis=1))
    # Rows increase downwards on the heatmap; the row tree must do the same.
    assert heatmap.get_ylim()[0] > heatmap.get_ylim()[1]
    row_trees = [ax for ax in _dendrogram_axis(fig) if ax.get_ylim()[0] != ax.get_ylim()[1]
                 and ax.get_position().x0 < heatmap.get_position().x0]
    assert row_trees, "no row dendrogram drawn left of the heatmap"
    for ax in row_trees:
        assert ax.get_ylim()[0] > ax.get_ylim()[1], "row dendrogram is drawn bottom-up, mirroring the heatmap"


def test_app_anova_heatmap_row_tree_reads_top_down():
    frame, metadata, samples = _frame()
    fig, plt = _anova_heatmap_figure(
        frame, metadata, kind="protein", advanced=None, label_column="ProteinNames",
        p_value_threshold=0.05, clustered=False, show_dendrograms=True, show_legend=False,
    )
    try:
        _assert_row_tree_matches_rows(fig, frame, samples)
    finally:
        plt.close(fig)


def test_pip_package_row_tree_reads_top_down():
    frame, metadata, samples = _frame()
    fig = notebook_functions.anova_plot(frame, metadata, show_dendrograms=True, width=6, height=5, dpi=60)
    try:
        _assert_row_tree_matches_rows(fig, frame, samples)
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)
