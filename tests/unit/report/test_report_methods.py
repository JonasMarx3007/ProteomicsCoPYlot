from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.summary import SummaryVolcanoEntry
from app.services.report_function import (
    _NORMALIZATION_REPORT_LABELS,
    _TEST_TYPE_REPORT_LABELS,
    _volcano_statistics_html,
)


def _text(html: str) -> str:
    import html as html_module

    return html_module.unescape(re.sub(r"<[^>]+>", "", html))


def _entry(**overrides) -> SummaryVolcanoEntry:
    values = {
        "kind": "protein",
        "condition1": "WT",
        "condition2": "KO",
        "testType": "unpaired",
        "useUncorrected": False,
        "pValueThreshold": 0.05,
        "log2fcThreshold": 1.0,
    }
    values.update(overrides)
    return SummaryVolcanoEntry(**values)


@pytest.mark.parametrize("test_type", sorted(_TEST_TYPE_REPORT_LABELS))
def test_every_test_type_is_named_in_the_report(test_type: str) -> None:
    text = _text(_volcano_statistics_html(_entry(testType=test_type)))
    assert _TEST_TYPE_REPORT_LABELS[test_type] in text


def test_all_supported_test_types_have_a_label() -> None:
    from app.services.functions import _TEST_TYPES

    assert set(_TEST_TYPES) == set(_TEST_TYPE_REPORT_LABELS)


def test_unknown_restored_imputation_is_not_reported_as_quantile_imputation(monkeypatch):
    from types import SimpleNamespace
    from app.schemas.annotation import AnnotationImputationInfo
    from app.services import report_function

    monkeypatch.setattr(report_function, "get_annotation", lambda kind: SimpleNamespace(
        imputation=AnnotationImputationInfo(mode="unknown", applied=True)))
    text = " ".join(report_function._imputation_paragraphs("protein"))
    assert "method and parameters are unknown" in text
    assert "sampled from" not in text and "seed 1337" not in text and "q =" not in text


def test_thresholds_are_stated() -> None:
    text = _text(_volcano_statistics_html(_entry(pValueThreshold=0.01, log2fcThreshold=1.5)))
    assert "0.01" in text and "1.5" in text


def test_corrected_and_uncorrected_are_distinguished() -> None:
    corrected = _text(_volcano_statistics_html(_entry(useUncorrected=False)))
    uncorrected = _text(_volcano_statistics_html(_entry(useUncorrected=True)))
    assert "Benjamini-Hochberg" in corrected
    assert "adjusted p <" in corrected
    assert "uncorrected" in uncorrected.lower()
    assert "Benjamini-Hochberg" not in uncorrected
    assert "adjusted p <" not in uncorrected


def test_all_normalization_methods_have_report_text() -> None:
    from app.schemas.annotation import NormalizationMethod
    import typing

    supported = set(typing.get_args(NormalizationMethod))
    assert supported == set(_NORMALIZATION_REPORT_LABELS)


def test_normalization_labels_distinguish_none_from_applied() -> None:
    assert _NORMALIZATION_REPORT_LABELS["none"].startswith("None;")
    for method in ("median", "quantile", "vsn"):
        label = _NORMALIZATION_REPORT_LABELS[method]
        assert not label.startswith("None")
        assert "applied globally, before filtering" in label
        assert label.strip().endswith(".")
