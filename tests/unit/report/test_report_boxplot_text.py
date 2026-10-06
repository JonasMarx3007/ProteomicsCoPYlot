"""The report's boxplot text describes the boxplot it sits next to.

It used to read "measured log2-raw protein intensities in a boxplot of each
sample" whatever was drawn: the default mode shows one box per condition of
per-protein means, the QC matrix is the normalized one, and zeros are only
treated as missing when the upload was on the linear scale. The first two
sentences are now written from the mode, the normalization (not mentioned when
none was applied) and the upload scale.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import report_function as report

GENERAL = ["old first", "old second", "Interpretation one.", "Interpretation two."]


@pytest.fixture
def annotation(monkeypatch):
    state = SimpleNamespace(filter_config=SimpleNamespace(normalization="none"), is_log2_transformed=True)
    monkeypatch.setattr(report, "get_annotation", lambda kind: state)
    monkeypatch.setattr(report, "GENERAL_COMMENTS", {"BoxplotIntProt": GENERAL, "BoxplotIntPhos": GENERAL})
    return state


def test_single_mode_is_one_box_per_sample(annotation):
    first, second, *rest = report._boxplot_comment_paragraphs("protein", "Single", "BoxplotIntProt")
    assert first == "Protein intensity distributions - Depicted are the log2 protein intensities, one box per sample."
    assert rest == GENERAL[2:], "the interpretation sentences follow unchanged"


def test_mean_mode_is_one_box_per_condition_of_feature_means(annotation):
    first, *_ = report._boxplot_comment_paragraphs("phospho", "Mean", "BoxplotIntPhos")
    assert first.startswith("Phosphosite intensity distributions - Depicted are the mean log2 intensities")
    assert "one box per condition" in first and "per sample" not in first.split(";")[0]


@pytest.mark.parametrize("normalization,word", [
    ("median", "median-normalized log2"), ("quantile", "quantile-normalized log2"), ("vsn", "VSN-transformed"),
])
def test_normalization_is_named_when_applied(annotation, normalization, word):
    annotation.filter_config.normalization = normalization
    first, *_ = report._boxplot_comment_paragraphs("protein", "Single", "BoxplotIntProt")
    assert f"the {word} protein intensities" in first


def test_no_normalization_is_not_mentioned(annotation):
    first, *_ = report._boxplot_comment_paragraphs("protein", "Single", "BoxplotIntProt")
    assert "normaliz" not in first.lower() and "raw" not in first


@pytest.mark.parametrize("uploaded_log2,mentions_zero", [(True, False), (False, True)])
def test_zero_sentence_only_for_linear_uploads(annotation, uploaded_log2, mentions_zero):
    annotation.is_log2_transformed = uploaded_log2
    _, second, *_ = report._boxplot_comment_paragraphs("protein", "Single", "BoxplotIntProt")
    assert second.startswith("Missing values are not considered")
    assert ("Zero intensities" in second) is mentions_zero
