"""The lines drawn over the data, rather than from it.

A coverage plot's total, a volcano's thresholds, a Q-Q fit, an identity line, a
regression fit, the imputation draw area: each of these used to hardcode its own
colour, dash and width, and two of them read a colour from the advanced panel
while their interactive twins ignored it -- so the same figure changed
appearance when the renderer changed. They all come through
`resolve_reference_line` now, and this is what holds them there.
"""

from __future__ import annotations

import pytest

from app.services.plot_styling import (
    ReferenceLine,
    resolve_reference_line,
)


def test_nothing_set_means_the_plot_keeps_its_own_look() -> None:
    line = resolve_reference_line({}, color="#9ca3af", style="dashed", width=0.8)
    assert line == ReferenceLine(visible=True, color="#9ca3af", style="dashed", width=0.8)


def test_the_panel_overrides_each_part_on_its_own() -> None:
    settings = {
        "referenceLineColor": "#112233",
        "referenceLineStyle": "dotted",
        "referenceLineWidth": 3,
    }
    line = resolve_reference_line(settings, color="red")
    assert (line.color, line.style, line.width) == ("#112233", "dotted", 3.0)
    assert line.visible is True


def test_the_line_can_be_switched_off() -> None:
    assert resolve_reference_line({"referenceLineVisible": False}).visible is False
    assert resolve_reference_line({"referenceLineVisible": True}).visible is True


def test_a_style_that_is_not_offered_falls_back_to_the_plot_s_own() -> None:
    line = resolve_reference_line({"referenceLineStyle": "squiggly"}, style="solid")
    assert line.style == "solid"


def test_a_negative_width_is_floored_rather_than_drawn() -> None:
    assert resolve_reference_line({"referenceLineWidth": -4}).width == 0.0


@pytest.mark.parametrize(
    ("style", "mpl", "plotly"),
    [
        ("solid", "-", "solid"),
        ("dashed", "--", "dash"),
        ("dotted", ":", "dot"),
        ("dashdot", "-.", "dashdot"),
    ],
)
def test_one_style_means_the_same_line_in_both_renderers(style: str, mpl: str, plotly: str) -> None:
    line = resolve_reference_line({"referenceLineStyle": style})
    assert line.matplotlib()["linestyle"] == mpl
    assert line.plotly()["dash"] == plotly


def test_both_renderers_are_given_the_same_colour_and_width() -> None:
    line = resolve_reference_line({"referenceLineColor": "#abcdef", "referenceLineWidth": 2})
    assert line.matplotlib()["color"] == line.plotly()["color"] == "#abcdef"
    assert line.matplotlib()["linewidth"] == line.plotly()["width"] == 2.0


# --- every renderer that draws a guide line --------------------------------------
#
# Each renderer below draws the example project (and, for the peptide plots, a
# small peptide file) three times: with no reference-line settings, with the
# switch off, and with a sentinel colour, width and style. Its figure is caught
# on the way to PNG or HTML and every straight line in it is listed. The guide
# lines are the ones the switch removes; each of them, and only they, must then
# take the sentinel. A line drawn in a hardcoded colour, or one that reads the
# colour setting but not the switch beside it, fails one of the two.

SENTINEL = {"referenceLineColor": "#123456", "referenceLineWidth": 2.75, "referenceLineStyle": "dotted"}
HIDDEN = {"referenceLineVisible": False}

SAMPLE_1 = "[6] 20240822_nElute_tims1_JM_HEK293_WP_WT_1_Slot1-61_1_8064.d.PG.Log2Quantity"
SAMPLE_2 = "[7] 20240822_nElute_tims1_JM_HEK293_WP_WT_2_Slot1-62_1_8065.d.PG.Log2Quantity"


def _renderers() -> dict:
    import pandas as pd

    from app.schemas.stats import VolcanoRequest
    from app.services import comparison_tools, peptide_tools, phospho_tools, plot_images, stats_tools

    kinases = pd.DataFrame(
        {"Kinase": ["AKT1", "MAPK1"], "Log2(Frequency Factor)": [1.5, -1.0], "Adjusted p-value": [0.01, 0.2]}
    )
    volcano = VolcanoRequest(kind="protein", condition1="WT", condition2="GRK")
    return {
        "pearson png": lambda adv: comparison_tools.pearson_correlation_png(
            "protein", sample1=SAMPLE_1, sample2=SAMPLE_2, advanced=adv),
        "pearson html": lambda adv: comparison_tools.pearson_correlation_html(
            "protein", sample1=SAMPLE_1, sample2=SAMPLE_2, advanced=adv),
        "retention time png": lambda adv: peptide_tools.peptide_rt_plot(add_line=True, advanced=adv),
        "retention time html": lambda adv: peptide_tools.peptide_rt_interactive_html(add_line=True, advanced=adv),
        "kinase library volcano": lambda adv: phospho_tools.ksea_uploaded_volcano_html(
            st_results=kinases, tnc_results=kinases, advanced=adv),
        "imputation fit and draw": lambda adv: plot_images.imputation_overall_fit_plot(
            "protein", 0.01, 0.3, 1337, True, advanced=adv),
        "q-q plot": lambda adv: plot_images.distribution_qqnorm_plot("protein", advanced=adv),
        "coverage": lambda adv: plot_images.qc_coverage_plot("protein", advanced=adv),
        "coverage summary": lambda adv: plot_images.qc_coverage_plot("protein", summary=True, advanced=adv),
        "peptide coverage": lambda adv: plot_images.qc_peptide_coverage_plot(advanced=adv),
        "volcano png": lambda adv: stats_tools.volcano_png(volcano, adv),
        "volcano html": lambda adv: stats_tools.volcano_html(volcano, adv),
    }


RENDERERS = list(_renderers())


def _straight_lines(fig) -> list[tuple[str, float, str | None]]:
    """(colour, width, style) of every line a figure draws, in either renderer."""
    import numpy as np
    from matplotlib.collections import LineCollection
    from matplotlib.colors import to_hex

    lines: list[tuple[str, float, str | None]] = []
    if hasattr(fig, "layout"):  # plotly: shapes (add_hline/add_vline) and line traces
        for shape in fig.layout.shapes or ():
            lines.append((str(shape.line.color), float(shape.line.width), shape.line.dash))
        for trace in fig.data:
            if "lines" in str(getattr(trace, "mode", "") or ""):
                lines.append((str(trace.line.color), float(trace.line.width), trace.line.dash))
        return lines
    for ax in fig.axes:
        for line in ax.lines:
            lines.append((to_hex(line.get_color()), round(float(line.get_linewidth()), 3), line.get_linestyle()))
        for collection in ax.collections:
            if isinstance(collection, LineCollection) and len(collection.get_segments()):
                width = round(float(np.atleast_1d(collection.get_linewidth())[0]), 3)
                lines.extend((to_hex(colour), width, None) for colour in collection.get_colors())
    return lines


@pytest.fixture
def drawn(example_project, monkeypatch, tmp_path):
    """Render a named plot with given settings and return its straight lines."""
    import matplotlib.pyplot as plt
    import pandas as pd

    from app.services import comparison_tools, peptide_tools, phospho_tools, plot_images, stats_tools
    from app.services.annotation_store import get_annotation
    from app.services.dataset_store import save_peptide_path
    from app.services.peptide_metadata_store import save_peptide_metadata

    metadata = get_annotation("protein").metadata.copy()
    peptides = tmp_path / "peptides.tsv"
    pd.DataFrame([
        {"File.Name": sample, "Stripped.Sequence": sequence, "Modified.Sequence": sequence,
         "Precursor.Id": sequence + "2", "Precursor.Quantity": float(i + 1),
         "RT": float(10 + i), "Predicted.RT": float(11 + i)}
        for sample in metadata["sample"] for i, sequence in enumerate(["AKR", "PEPTIDEK", "MPEPRK"])
    ]).to_csv(peptides, sep="\t", index=False)
    save_peptide_path(str(peptides))
    save_peptide_metadata("metadata.csv", metadata)

    caught: dict = {}

    def catch_png(fig, *args, **kwargs):
        caught["fig"] = fig
        return b"png"

    def catch_html(fig):
        caught["fig"] = fig
        return "<div></div>"

    for module in (comparison_tools, peptide_tools, phospho_tools, plot_images, stats_tools):
        monkeypatch.setattr(module, "_to_png_bytes", catch_png)
        monkeypatch.setattr(module, "_plotly_html", catch_html)

    renderers = _renderers()

    def draw(name: str, settings: dict) -> list:
        caught.clear()
        renderers[name](dict(settings))
        lines = _straight_lines(caught["fig"])
        plt.close("all")
        return lines

    return draw


@pytest.mark.parametrize("name", RENDERERS)
def test_every_guide_line_is_drawn_behind_the_visibility_switch(drawn, name: str) -> None:
    """The switch removes at least one line, and the plot draws it again when on."""
    shown, hidden = drawn(name, {}), drawn(name, HIDDEN)
    assert len(shown) > len(hidden), f"{name}: turning the reference line off removed nothing"
    assert set(hidden) <= set(shown), f"{name}: turning the line off changed other lines: {hidden}"


@pytest.mark.parametrize("name", RENDERERS)
def test_no_guide_line_is_drawn_in_a_colour_the_panel_cannot_reach(drawn, name: str) -> None:
    """Every line the switch governs takes the panel's colour, width and style."""
    guides = len(drawn(name, {})) - len(drawn(name, HIDDEN))
    styled = drawn(name, SENTINEL)
    followed = [line for line in styled if line[0] == SENTINEL["referenceLineColor"]]
    assert len(followed) == guides, (
        f"{name}: {guides} guide line(s), but {len(followed)} took the panel's colour: {styled}"
    )
    for _, width, style in followed:
        assert width == SENTINEL["referenceLineWidth"], f"{name}: width {width} ignores the panel"
        assert style in {":", "dot", None}, f"{name}: style {style!r} ignores the panel"
