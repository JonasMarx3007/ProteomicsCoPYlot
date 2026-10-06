"""The static volcano shows the same numbers as the interactive one.

Two renderers over one dataframe is how the PCA works, and it is only safe
while both draw the same points. `_volcano_dataframe` is shared, so the risk is
not the arithmetic -- it is that the static path filters, rounds or drops
something on its way to the canvas, which no amount of looking at the picture
would reveal.

The label placement gets its own tests because it is the one piece with real
logic in it: it decides which labels are drawn at all.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services import stats_tools


@pytest.fixture
def volcano_frame() -> pd.DataFrame:
    """A volcano-shaped frame: two tails and a large non-significant cloud."""
    rng = np.random.default_rng(20260916)
    size = 300
    frame = pd.DataFrame(
        {
            "ProteinNames": [f"P{index:04d}" for index in range(size)],
            "log2FC": rng.normal(0, 0.4, size),
            "neg_log10_selected_pval": rng.uniform(0, 1.2, size),
        }
    )
    frame["significance"] = "Not significant"
    frame.loc[:19, ["log2FC", "neg_log10_selected_pval", "significance"]] = None
    frame.loc[:19, "log2FC"] = rng.uniform(1.2, 3.0, 20)
    frame.loc[:19, "neg_log10_selected_pval"] = rng.uniform(2.0, 6.0, 20)
    frame.loc[:19, "significance"] = "Upregulated"
    frame.loc[20:39, "log2FC"] = rng.uniform(-3.0, -1.2, 20)
    frame.loc[20:39, "neg_log10_selected_pval"] = rng.uniform(2.0, 6.0, 20)
    frame.loc[20:39, "significance"] = "Downregulated"
    return frame


def _render(frame: pd.DataFrame, **kwargs):
    defaults = dict(
        label_column="ProteinNames",
        condition1="A",
        condition2="B",
        p_value_threshold=0.05,
        log2fc_threshold=1.0,
        use_uncorrected=False,
        highlight_terms=[],
    )
    defaults.update(kwargs)
    return stats_tools._volcano_png_figure(frame, **defaults)


def _plotted_points(ax) -> np.ndarray:
    offsets = [collection.get_offsets() for collection in ax.collections]
    return np.vstack([np.asarray(item) for item in offsets if len(item)])


# --- the same points as the dataframe ------------------------------------------


def test_every_feature_reaches_the_figure(volcano_frame) -> None:
    """No silent filtering: what the table holds is what the figure draws."""
    fig, plt = _render(volcano_frame)
    try:
        drawn = _plotted_points(fig.axes[0])
        assert len(drawn) == len(volcano_frame)
        expected = set(
            zip(
                np.round(volcano_frame["log2FC"].astype(float), 9),
                np.round(volcano_frame["neg_log10_selected_pval"].astype(float), 9),
            )
        )
        assert set(zip(np.round(drawn[:, 0], 9), np.round(drawn[:, 1], 9))) == expected
    finally:
        plt.close(fig)


def test_each_class_is_its_own_mark(volcano_frame) -> None:
    """Three classes, three collections -- so each can be sized on its own."""
    fig, plt = _render(volcano_frame)
    try:
        sizes = {
            float(collection.get_sizes()[0])
            for collection in fig.axes[0].collections
            if len(collection.get_sizes())
        }
        # Not-significant is smaller than the two tails by default.
        assert len(sizes) == 2, sizes
        assert min(sizes) == stats_tools.marker_area(5.0)
        assert max(sizes) == stats_tools.marker_area(6.0)
    finally:
        plt.close(fig)


def test_the_advanced_panel_sizes_each_class(volcano_frame) -> None:
    fig, plt = _render(
        volcano_frame,
        advanced={"volcanoUpSize": 12, "volcanoDownSize": 3, "volcanoNsSize": 1},
    )
    try:
        sizes = sorted(
            float(collection.get_sizes()[0])
            for collection in fig.axes[0].collections
            if len(collection.get_sizes())
        )
        assert sizes == [
            stats_tools.marker_area(1),
            stats_tools.marker_area(3),
            stats_tools.marker_area(12),
        ]
    finally:
        plt.close(fig)


def test_opacity_is_per_class_and_clamped(volcano_frame) -> None:
    """An opacity outside 0..1 is a typo, not an instruction."""
    fig, plt = _render(volcano_frame, advanced={"volcanoNsAlpha": 0, "volcanoUpAlpha": 40})
    try:
        alphas = {collection.get_alpha() for collection in fig.axes[0].collections}
        assert 0.0 in alphas and 1.0 in alphas
    finally:
        plt.close(fig)


# --- the styling that makes it a figure for print ------------------------------


def test_the_frame_is_two_spines_and_no_grid(volcano_frame) -> None:
    fig, plt = _render(volcano_frame)
    try:
        ax = fig.axes[0]
        assert not ax.spines["top"].get_visible()
        assert not ax.spines["right"].get_visible()
        assert ax.spines["left"].get_visible()
        assert ax.spines["bottom"].get_visible()
        assert not any(line.get_visible() for line in ax.get_xgridlines())
        assert not any(line.get_visible() for line in ax.get_ygridlines())
    finally:
        plt.close(fig)


def test_the_thresholds_are_drawn_where_they_were_asked_for(volcano_frame) -> None:
    fig, plt = _render(volcano_frame, log2fc_threshold=1.5, p_value_threshold=0.01)
    try:
        ax = fig.axes[0]
        verticals = sorted(
            line.get_xdata()[0]
            for line in ax.lines
            if len(set(line.get_xdata())) == 1
        )
        assert verticals == [-1.5, 1.5]
        horizontal = [
            line.get_ydata()[0] for line in ax.lines if len(set(line.get_ydata())) == 1
        ]
        assert horizontal == pytest.approx([-np.log10(0.01)])
    finally:
        plt.close(fig)


# --- labelling -----------------------------------------------------------------


def test_nothing_is_labelled_unless_asked(volcano_frame) -> None:
    """A volcano of thousands has no readable set of labels chosen for you."""
    fig, plt = _render(volcano_frame)
    try:
        assert [text for text in fig.axes[0].texts if text.get_text()] == []
    finally:
        plt.close(fig)


def test_the_labels_are_the_most_significant_in_each_direction(volcano_frame) -> None:
    fig, plt = _render(volcano_frame, label_top_up=3, label_top_down=2)
    try:
        drawn = {text.get_text() for text in fig.axes[0].texts if text.get_text()}
        expected = set(
            stats_tools._volcano_top_hits(
                volcano_frame, label_column="ProteinNames", up=3, down=2
            )["ProteinNames"]
        )
        # Placement may drop a label it cannot fit; it may never invent one.
        assert drawn <= expected
        assert drawn
    finally:
        plt.close(fig)


def test_labels_never_overlap_each_other(volcano_frame) -> None:
    """The whole reason the placement exists.

    Twenty labels on points metres apart in data space and millimetres apart on
    the page is the case that produced an unreadable smear at the top of the
    figure, which is exactly where the reader is looking.
    """
    fig, plt = _render(volcano_frame, label_top_up=20, label_top_down=20)
    try:
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        boxes = [
            text.get_window_extent(renderer=renderer)
            for text in fig.axes[0].texts
            if text.get_text()
        ]
        assert len(boxes) >= 2
        for left in range(len(boxes)):
            for right in range(left + 1, len(boxes)):
                assert not boxes[left].overlaps(boxes[right]), (
                    f"label {left} overlaps label {right}"
                )
    finally:
        plt.close(fig)


def test_a_pair_asked_for_in_one_direction_only(volcano_frame) -> None:
    hits = stats_tools._volcano_top_hits(
        volcano_frame, label_column="ProteinNames", up=4, down=0
    )
    assert set(hits["significance"]) == {"Upregulated"}
    assert len(hits) == 4


def test_top_hits_are_ranked_by_the_axis_the_reader_sees(volcano_frame) -> None:
    hits = stats_tools._volcano_top_hits(
        volcano_frame, label_column="ProteinNames", up=5, down=0
    )
    upregulated = volcano_frame[volcano_frame["significance"] == "Upregulated"]
    highest = upregulated.nlargest(5, "neg_log10_selected_pval")["ProteinNames"]
    assert set(hits["ProteinNames"]) == set(highest)


# --- refusals ------------------------------------------------------------------


def test_an_empty_frame_still_renders(volcano_frame) -> None:
    """A comparison with nothing in it produces an empty plot, not a traceback."""
    fig, plt = _render(volcano_frame.head(0), label_top_up=5, label_top_down=5)
    try:
        assert fig.axes[0] is not None
    finally:
        plt.close(fig)
