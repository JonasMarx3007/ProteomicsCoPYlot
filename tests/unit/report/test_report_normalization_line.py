"""Normalization is stated on its own line, never under "Not applied".

The normalization sentence used to be the tail of the filtering description, so
a plot on the unfiltered "Data" source -- every QC plot -- was headed
"Filtering: Not applied to this plot. ... Samples were median-centred ...",
which reads as though the centring was skipped too. It never is: normalization
is fitted on the filtered rows and applied to the whole log2 matrix.
"""

from __future__ import annotations

import html as html_module
import re
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

import app.services.report_function as report


def _lines(markup: str) -> list[str]:
    return [html_module.unescape(re.sub(r"<[^>]+>", "", p)) for p in re.findall(r"<p>(.*?)</p>", markup)]


def _annotation(normalization: str):
    return SimpleNamespace(
        filter_config=SimpleNamespace(
            method="at_least_n", mode="in_at_least_one_group", minPresent=3, normalization=normalization,
        ),
        filtered_data=pd.DataFrame({"v": range(7450)}),
        source_data=pd.DataFrame({"v": range(7490)}),
        imputation=None,
        imputed_data=pd.DataFrame(),
    )


@pytest.mark.parametrize("normalization, phrase", [
    ("median", "median-centred"),
    ("quantile", "quantile-normalized"),
    ("vsn", "Variance-stabilizing"),
])
def test_unfiltered_plots_state_normalization_as_applied(monkeypatch, normalization, phrase) -> None:
    monkeypatch.setattr(report, "get_annotation", lambda kind: _annotation(normalization))
    lines = _lines(report._data_provenance_html(kind="protein", data_source="data", subject="this plot"))
    assert lines[0] == "Data source: Unfiltered Data"
    assert lines[1].startswith("Normalization: ") and phrase in lines[1]
    assert "Not applied" not in lines[1]
    assert lines[2].startswith("Filtering: Not applied to this plot; it uses all 7490 rows.")
    assert "keeps 7450 rows" in lines[2]
    # The full recipe is not repeated for a plot that skipped the filter.
    assert "at least 3 valid values" not in lines[2]
    assert normalization not in lines[2].lower()


def test_no_normalization_means_no_normalization_line(monkeypatch) -> None:
    """"none" usually means the upload was normalized upstream; a line saying
    it was not applied reads as though a step was skipped, so nothing is printed."""
    monkeypatch.setattr(report, "get_annotation", lambda kind: _annotation("none"))
    lines = _lines(report._data_provenance_html(kind="protein", data_source="data", subject="this plot"))
    assert not any(line.startswith("Normalization:") for line in lines)
    assert lines[1].startswith("Filtering: Not applied to this plot")


def test_filtered_plots_carry_the_recipe_and_the_counts(monkeypatch) -> None:
    monkeypatch.setattr(report, "get_annotation", lambda kind: _annotation("median"))
    lines = _lines(report._data_provenance_html(kind="protein", data_source="filtered", subject="this plot"))
    assert lines[1].startswith("Normalization: Samples were median-centred")
    assert lines[2] == (
        "Filtering: Rows with at least 3 valid values in at least one condition group "
        "were retained (7450 of 7490 rows)."
    )


def test_the_filter_sentence_no_longer_mentions_normalization() -> None:
    text = report._filter_description(_annotation("quantile"))
    assert "quantile" not in text.lower()
    assert "normaliz" not in text.lower()


@pytest.mark.parametrize("method, field", [("at_least_n", "minPresent"), ("percentage", "minPercentage")])
def test_a_zero_threshold_is_reported_as_no_filtering(monkeypatch, method, field) -> None:
    """Requiring 0 valid values (or 0 %) keeps every row, so it is no filter.

    The default configuration is exactly that, and the report used to describe
    it as "rows with at least 0 valid values ... were retained".
    """
    annotation = _annotation("median")
    annotation.filter_config = SimpleNamespace(
        method=method, mode="in_at_least_one_group", minPresent=0, minPercentage=0.0, normalization="median",
    )
    annotation.filtered_data = annotation.source_data
    monkeypatch.setattr(report, "get_annotation", lambda kind: annotation)
    assert report._filter_description(annotation) == "No completeness filter was applied (all 7490 rows retained)."
    for source in ("data", "filtered"):
        lines = _lines(report._data_provenance_html(kind="protein", data_source=source, subject="this plot"))
        assert lines[2] == "Filtering: No completeness filter was applied (all 7490 rows retained)."
        assert "at least 0" not in " ".join(lines)
        assert "Not applied to this plot" not in " ".join(lines)


def test_a_positive_threshold_is_still_a_filter() -> None:
    annotation = _annotation("none")
    assert report._filter_description(annotation).startswith("Rows with at least 3 valid values")
    annotation.filter_config = SimpleNamespace(
        method="percentage", mode="overall", minPresent=0, minPercentage=70.0, normalization="none",
    )
    assert report._filter_description(annotation).startswith("Rows with at least 70% completeness")
