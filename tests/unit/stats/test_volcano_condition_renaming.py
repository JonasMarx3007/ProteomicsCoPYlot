"""A condition renamed in the plot appearance panel reaches the whole volcano.

`conditionLabels` is offered on the volcano, and both renderers built their
title and their fold-change axis label straight from the raw condition names --
so the reader saw the name they had chosen in the panel and a different name on
the figure, on the one plot whose axis label is the statement of what was
computed.

Renaming changes the *names*. It must not touch the sign convention: the axis
still states condition 1 minus condition 2, which `comparison_contrast` owns.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services import stats_tools
from app.services.functions import comparison_contrast

RENAMES = {"conditionLabels": {"A": "Treated", "B": "Untreated", "C": "Vehicle", "D": "Mock"}}


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ProteinNames": ["P1", "P2", "P3"],
            "log2FC": [2.0, -2.0, 0.1],
            "neg_log10_selected_pval": [4.0, 4.0, 0.2],
            "significance": ["Upregulated", "Downregulated", "Not significant"],
        }
    )


def _static(frame: pd.DataFrame, **kwargs) -> tuple[str, str]:
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
    fig, plt = stats_tools._volcano_png_figure(frame, **defaults)
    try:
        ax = fig.axes[0]
        return ax.get_title(), ax.get_xlabel()
    finally:
        plt.close(fig)


def _interactive(frame: pd.DataFrame, **kwargs) -> tuple[str, str]:
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
    figure = stats_tools._volcano_figure(frame, **defaults)
    return str(figure.layout.title.text), str(figure.layout.xaxis.title.text)


RENDERERS = pytest.mark.parametrize(
    "render", [_static, _interactive], ids=["static", "interactive"]
)


@RENDERERS
def test_the_plain_volcano_titles_and_axis_use_the_renamed_conditions(frame, render) -> None:
    title, axis = render(frame, advanced=RENAMES)
    assert title == "Treated vs Untreated"
    assert axis == "log2 fold change (Treated - Untreated)"
    # The raw names are gone from both, not merely joined by the new ones.
    for text in (title, axis):
        assert "A" not in text.split() and "B" not in text.split(), text


@RENDERERS
def test_the_control_volcano_renames_all_four_conditions(frame, render) -> None:
    title, axis = render(
        frame, condition1_control="C", condition2_control="D", advanced=RENAMES
    )
    assert title == "Treated vs Untreated (controls: Vehicle vs Mock)"
    assert axis == "log2 fold change ((Treated - Vehicle) - (Untreated - Mock))"


@RENDERERS
def test_renaming_does_not_move_the_minuend(frame, render) -> None:
    """Only the names change: condition 1 is still the one subtracted from."""
    _, axis = render(
        frame, condition1_control="C", condition2_control="D", advanced=RENAMES
    )
    expected = comparison_contrast("Treated", "Untreated", "Vehicle", "Mock")
    assert axis == f"log2 fold change ({expected})"
    reversed_form = comparison_contrast("Untreated", "Treated", "Mock", "Vehicle")
    assert reversed_form not in axis


@RENDERERS
def test_an_unrenamed_condition_keeps_its_own_name(frame, render) -> None:
    title, axis = render(frame, advanced={"conditionLabels": {"A": "Treated"}})
    assert title == "Treated vs B"
    assert axis == "log2 fold change (Treated - B)"


@RENDERERS
def test_no_panel_settings_leaves_the_texts_untouched(frame, render) -> None:
    title, axis = render(frame, advanced=None)
    assert title == "A vs B"
    assert axis == "log2 fold change (A - B)"


def test_both_renderers_write_the_same_two_texts(frame) -> None:
    """One helper, so the figure for the paper and the one on screen agree."""
    for kwargs in (
        {"advanced": RENAMES},
        {"advanced": RENAMES, "condition1_control": "C", "condition2_control": "D"},
        {"advanced": None},
    ):
        assert _static(frame, **kwargs) == _interactive(frame, **kwargs)


def test_the_empty_volcano_still_gets_its_renamed_texts() -> None:
    empty = pd.DataFrame(
        {
            "ProteinNames": pd.Series(dtype=str),
            "log2FC": pd.Series(dtype=float),
            "neg_log10_selected_pval": pd.Series(dtype=float),
            "significance": pd.Series(dtype=str),
        }
    )
    assert _static(empty, advanced=RENAMES)[0] == "Treated vs Untreated"
    assert _interactive(empty, advanced=RENAMES)[0] == "Treated vs Untreated"
