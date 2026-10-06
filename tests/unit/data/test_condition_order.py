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
