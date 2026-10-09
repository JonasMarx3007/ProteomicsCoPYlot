"""Two switches that moved into the plots' own options.

The coverage plot's total line is switched in the coverage options; off, it is
not drawn and the 10 % headroom is measured from the tallest bar. The ANOVA cluster heatmaps can
name their rows; the names sit right of the heatmap, clear of the colour bar.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from app.services import plot_images, stats_tools  # noqa: E402


@pytest.fixture
def coverage_figures(monkeypatch):
    frame = pd.DataFrame(
        {
            "ProteinNames": [f"P{i}" for i in range(10)],
            "a1": [1.0] * 6 + [np.nan] * 4,
            "a2": [1.0] * 5 + [np.nan] * 5,
            "b1": [np.nan] * 3 + [1.0] * 7,
            "b2": [np.nan] * 2 + [1.0] * 8,
        }
    )
    samples = ["a1", "a2", "b1", "b2"]
    meta = pd.DataFrame({"sample": samples, "condition": ["A", "A", "B", "B"]})
    monkeypatch.setattr(plot_images, "log2_qc_frame", lambda kind: frame)
    monkeypatch.setattr(plot_images, "_get_sample_columns", lambda kind, df: samples)
    monkeypatch.setattr(plot_images, "_metadata_for_kind", lambda kind, df, cols: meta.copy())
    monkeypatch.setattr(
        plot_images,
        "advanced_condition_colors",
        lambda kind, plt, conditions, advanced: {c: "#1f77b4" for c in conditions},
    )
    captured = []

    def fake_png(fig, plt, **_kwargs):
        captured.append(fig)
        return b""

    monkeypatch.setattr(plot_images, "_to_png_bytes", fake_png)
    return captured


def _hlines(ax):
    return [line for line in ax.get_lines() if len(set(line.get_ydata())) == 1 and line.get_xdata()[0] == 0]


def test_coverage_draws_the_total_line_by_default(coverage_figures):
    plot_images.qc_coverage_plot(kind="protein")
    ax = coverage_figures[-1].axes[0]
    assert _hlines(ax), "the total line is part of the plot unless switched off"
    # 10 proteins quantified somewhere; the axis leaves room for the line.
    assert ax.get_ylim()[1] == pytest.approx(10 * 1.1)


def test_coverage_without_the_line_fits_the_bars(coverage_figures):
    plot_images.qc_coverage_plot(kind="protein", reference_line=False)
    ax = coverage_figures[-1].axes[0]
    assert not _hlines(ax)
    # The tallest bar is 8: the same 10 % headroom, measured from the bar.
    assert ax.get_ylim()[1] == pytest.approx(8 * 1.1)


def test_count_labels_keep_their_headroom_without_the_line(coverage_figures):
    # Count labels stand on top of the bars since 2026-10-09, so the axis
    # leaves 25 % instead of 10 % above the tallest bar.
    plot_images.qc_coverage_plot(kind="protein", reference_line=False, text=True)
    assert coverage_figures[-1].axes[0].get_ylim()[1] == pytest.approx(8 * 1.25)


def _cluster_frame(rows: int = 12):
    rng = np.random.default_rng(3)
    return pd.DataFrame(
        {
            "GeneNames": [f"GENE{i}" for i in range(rows)],
            "s1": rng.normal(size=rows),
            "s2": rng.normal(size=rows),
            "s3": rng.normal(size=rows),
            "s4": rng.normal(size=rows),
            "adj_pval": np.full(rows, 0.01),
            "cluster": [1 + i % 3 for i in range(rows)],
        }
    )


def _heatmap(**kwargs):
    metadata = pd.DataFrame({"sample": ["s1", "s2", "s3", "s4"], "condition": ["a", "a", "b", "b"]})
    figure, plt = stats_tools._anova_heatmap_figure(
        _cluster_frame(),
        metadata,
        kind="protein",
        label_column="GeneNames",
        p_value_threshold=0.05,
        clustered=True,
        show_dendrograms=True,
        show_legend=True,
        **kwargs,
    )
    heatmap = next(ax for ax in figure.axes if ax.get_xlabel() == "samples")
    return figure, plt, heatmap


def test_cluster_heatmap_has_no_row_labels_unless_asked(monkeypatch):
    monkeypatch.setattr(
        stats_tools, "advanced_condition_colors", lambda kind, plt, conditions, advanced: {}
    )
    figure, plt, heatmap = _heatmap(advanced=None)
    assert [t.get_text() for t in heatmap.get_yticklabels()] == []
    plt.close(figure)


def test_cluster_heatmap_names_its_rows_clear_of_the_colour_bar(monkeypatch):
    monkeypatch.setattr(
        stats_tools, "advanced_condition_colors", lambda kind, plt, conditions, advanced: {}
    )
    figure, plt, heatmap = _heatmap(
        advanced={"rowLabelColor": "#ff0000", "rowLabelSize": 6}, row_labels=True
    )
    labels = heatmap.get_yticklabels()
    assert [t.get_text() for t in labels] == [f"GENE{i}" for i in range(12)]
    assert all(t.get_fontsize() == 6 for t in labels)
    assert all(matplotlib.colors.to_hex(t.get_color()) == "#ff0000" for t in labels)

    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    colour_bar = next(ax for ax in figure.axes if ax.get_ylabel() == "row z-score")
    right_edge = max(t.get_window_extent(renderer).x1 for t in labels)
    assert right_edge <= colour_bar.get_window_extent(renderer).x0
    plt.close(figure)
