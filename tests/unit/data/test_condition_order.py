"""Conditions appear in the order the metadata lists them, on every page.

The plots drew conditions in metadata order while the statistics, single-protein
and phosphosite selectors sorted them alphabetically, so the example project
showed WT before GRK in every figure and GRK before WT in every list beside it.
Metadata order is the one the user chose; it is now the only one. The example's
metadata lists WT first, and alphabetical order would put GRK first, so either
mistake shows here.
"""
from __future__ import annotations

import re

import matplotlib
import pytest

METADATA_ORDER = ["WT", "GRK"]


def test_the_example_would_tell_the_two_orders_apart(example_project) -> None:
    from app.services.annotation_store import get_annotation

    listed = get_annotation("protein").metadata["condition"].astype(str).drop_duplicates().tolist()
    assert listed == METADATA_ORDER and sorted(listed) != METADATA_ORDER


@pytest.mark.parametrize("path,field", [
    ("/api/stats/options/protein", "availableConditions"),
    ("/api/stats/options/phospho", "availableConditions"),
    ("/api/plots/qc/protein/options", "conditions"),
    ("/api/plots/single-protein/protein/options", "conditions"),
    ("/api/plots/single-protein/phospho/options", "conditions"),
    ("/api/plots/phospho/options", "conditions"),
    ("/api/plots/comparison/protein/options", "conditions"),
])
def test_every_selector_lists_them_in_metadata_order(client, path: str, field: str) -> None:
    response = client.get(path)
    assert response.status_code == 200, response.text[:300]
    assert response.json()[field] == METADATA_ORDER


def test_the_samples_by_condition_follow_the_same_order(client) -> None:
    assert list(client.get("/api/stats/options/protein").json()["samplesByCondition"]) == METADATA_ORDER


@pytest.mark.parametrize("path,params", [
    ("/api/plots/qc/protein/boxplot.png", {"mode": "Mean"}),
    ("/api/plots/stats/protein/anova.png", {}),
    ("/api/plots/single-protein/protein/boxplot.png", {"protein": "1433B_HUMAN", "conditions": "[]"}),
])
def test_the_figures_draw_them_in_that_order_too(client, monkeypatch, path: str, params: dict) -> None:
    # Text kept as text in the SVG, so the labels can be read in drawing order.
    monkeypatch.setitem(matplotlib.rcParams, "svg.fonttype", "none")
    response = client.get(path, params={**params, "downloadFormat": "svg"})
    assert response.status_code == 200, response.text[:300]
    labels = [re.match(r"(WT|GRK)\b", text).group(1)
              for text in re.findall(r">([^<>]*)</text>", response.text) if re.match(r"(WT|GRK)\b", text)]
    assert labels[:2] == METADATA_ORDER, labels


def test_the_comparison_options_carry_the_plot_label_of_every_sample(client) -> None:
    """Single-sample Venn and Pearson plots used to be titled with the full run
    name unless an alias was typed; the page now prefills the alias with the
    `WT_1`-style label every QC plot draws, which the options hand over here."""
    body = client.get("/api/plots/comparison/protein/options").json()
    labels = body["sampleLabels"]
    assert set(labels) == set(body["samples"])
    for sample, label in labels.items():
        condition, number = label.rsplit("_", 1)
        assert condition in body["conditions"] and number.isdigit()
        assert label != sample


def test_venn_set_names_are_a_key_under_the_circles(monkeypatch):
    # 2026-10-09: long condition names collided at the circle edges; the names
    # are a legend under the diagram now, one swatch per set.
    from app.services import comparison_tools

    monkeypatch.setattr(comparison_tools, "_venn_sets",
                        lambda **k: ({"a", "b"}, {"b", "c"}, {"c", "d"} if k.get("third") else None))
    captured = {}

    def capture(fig, plt, **kwargs):
        captured["fig"] = fig
        return b"png"
    monkeypatch.setattr(comparison_tools, "_to_png_bytes", capture)
    render = getattr(comparison_tools.venn_png, "__wrapped__", comparison_tools.venn_png)
    render(kind="protein", mode="Condition", first="WT", second="GRK knockout", third="Third",
           alias1="", alias2="", alias3="", color1="#1f77b4", color2="#ff7f0e", color3="#2ca02c",
           header=True, width_cm=12, height_cm=10, dpi=72)
    ax = captured["fig"].axes[0]
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["WT", "GRK knockout", "Third"]
    assert not [t for t in ax.texts if t.get_visible() and t.get_text() in {"WT", "GRK knockout", "Third"}]
