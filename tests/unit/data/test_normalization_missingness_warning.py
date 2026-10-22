"""Annotation warns when normalization meets very uneven missingness; the report does not.

See tests/parity/test_missingness_imbalance.py for the rule itself and the
agreement between the three implementations. In the app the warning belongs to
the annotation's warning list, shown in the amber notice on the annotation page
while the normalization is being chosen. The report records what was done by
someone who has seen that notice, so it carries no warning.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.schemas.summary import SummaryReportContext, SummaryReportRequest
from app.services.annotation_processor import compute_annotation_from_metadata
from app.services.functions import filter_data, missingness_imbalance, missingness_imbalance_warning, normalize_data

report = importlib.import_module("app.services.report_function")


def _simulated(missing_b: float = 0.30) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(11)
    samples = ["A1", "A2", "A3", "B1", "B2", "B3"]
    base = rng.normal(22, 2.5, 400)
    values = {}
    for sample in samples:
        column = base + rng.normal(0, 0.3, base.size)
        share = missing_b if sample.startswith("B") else 0.05
        column[column < np.quantile(column, share)] = np.nan
        values[sample] = column
    frame = pd.DataFrame({"Protein": [f"P{i}" for i in range(base.size)], **values})
    return frame, pd.DataFrame({"sample": samples, "condition": [s[0] for s in samples]})


def _missingness_warnings(frame, meta, normalization):
    result = compute_annotation_from_metadata(frame, meta, True, 1, "in at least one group",
                                              normalization=normalization)
    return [warning for warning in result.warnings if warning.startswith("Missing values differ strongly")]


@pytest.mark.parametrize("normalization", ["median", "quantile"])
def test_annotation_warns_for_median_and_quantile(normalization):
    frame, meta = _simulated()
    found = _missingness_warnings(frame, meta, normalization)
    # The warning describes what the fit saw: the rows the filter kept.
    kept = filter_data(normalize_data(frame, meta, normalization), meta, 1, "in_at_least_one_group")
    expected = missingness_imbalance_warning(missingness_imbalance(kept, meta), normalization)
    assert found == [expected + ' To remove the shift, fit the normalization on the features observed in every sample (Normalization box, "Fit on").']
    assert "B1 (" in found[0] and "All of them are in condition B" in found[0]


def test_annotation_stays_quiet_without_normalization_or_imbalance():
    frame, meta = _simulated()
    assert _missingness_warnings(frame, meta, "none") == []
    balanced, meta = _simulated(missing_b=0.05)
    assert _missingness_warnings(balanced, meta, "median") == []


def _annotation(normalization: str, missing_b: float = 0.30):
    frame, meta = _simulated(missing_b)
    log2 = normalize_data(frame, meta, normalization)
    return SimpleNamespace(
        metadata=meta, source_data=frame, log2_data=log2, filtered_data=log2,
        filter_config=SimpleNamespace(method="at_least_n", mode="in at least one group", minPresent=1,
                                      normalization=normalization),
        imputation=None,
    )


def _report_html(monkeypatch, annotation) -> str:
    monkeypatch.setattr(report, "get_annotation", lambda kind: annotation if kind == "protein" else None)
    monkeypatch.setattr(report, "get_current_dataset", lambda kind: object() if kind == "protein" else None)

    def renderer(name):
        def render(*args, **kwargs):
            if name.endswith("_table"):
                return pd.DataFrame({"Label": ["x"], "Value": [1]})
            return "<div></div>" if name.endswith("_html") else b"png"
        return render

    for name in [n for n in vars(report) if n.startswith(("qc_", "peptide_")) or n in (
            "completeness_missing_value_plot", "phospho_coverage_png", "phosphosite_plot_png", "volcano_html")]:
        if callable(getattr(report, name)):
            monkeypatch.setattr(report, name, renderer(name))
    result = report.report_function(SummaryReportRequest(title="t", author="a", reportContext=SummaryReportContext()))
    return result.html


@pytest.mark.parametrize("normalization", ["median", "quantile"])
def test_the_report_carries_no_missingness_warning(monkeypatch, normalization):
    html = _report_html(monkeypatch, _annotation(normalization))
    assert "<strong>Normalization:</strong>" in html
    assert "Missing values differ strongly" not in html


def test_annotation_warns_for_vsn(monkeypatch):
    """VSN is fitted on each sample's observed values too, so the same imbalance concerns it."""
    monkeypatch.setattr("app.services.r_vsn.vsn_normalize_linear", lambda data, **kw: np.log2(data))
    frame, meta = _simulated()
    linear = frame.copy()
    linear[meta["sample"]] = np.power(2.0, linear[meta["sample"]])
    result = compute_annotation_from_metadata(linear, meta, False, 1, "in at least one group",
                                              normalization="vsn")
    found = [w for w in result.warnings if w.startswith("Missing values differ strongly")]
    assert len(found) == 1 and "VSN uses each sample's observed values" in found[0]
