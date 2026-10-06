"""The completeness page leaves out features with no value in any selected sample.

The missing-value plot already did (identified elsewhere, never quantified here:
they say nothing about the selected samples); the sample table, the feature
table and the overall percentage counted them in their denominators, so the same
page showed different totals. Now one selection step serves plot, heatmap and
tables, the response says how many rows were left out, and the report states it.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from app.services import completeness_tools, report_function  # noqa: E402

SAMPLES = ["A1", "A2", "B1", "B2"]


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ProteinNames": ["full", "one_gap", "two_gaps", "never_here", "never_here_2"],
            "A1": [1.0, 1.0, np.nan, np.nan, np.nan],
            "A2": [1.0, 1.0, 1.0, np.nan, np.nan],
            "B1": [1.0, np.nan, np.nan, np.nan, np.nan],
            "B2": [1.0, 1.0, 1.0, np.nan, np.nan],
            "Z9_unselected": [1.0, 1.0, 1.0, 1.0, np.nan],
        }
    )


@pytest.fixture
def loaded(monkeypatch):
    meta = pd.DataFrame({"sample": SAMPLES, "condition": ["A", "A", "B", "B"]})
    monkeypatch.setattr(completeness_tools, "_frame_and_meta", lambda kind: (_frame(), meta.copy()))
    return meta


def test_tables_and_plot_count_the_same_rows(loaded):
    tables = completeness_tools.completeness_tables("protein", include_id=False)
    assert tables.excludedAllMissingCount == 2
    feature_rows = {int(r["n_MissingProteinValues"]): int(r["Counts"]) for r in tables.featureSummary}
    assert feature_rows == {0: 1, 1: 1, 2: 1}  # no "4 missing" bucket
    assert sum(feature_rows.values()) == 3
    sample = {r["Sample"]: r for r in tables.sampleSummary}
    # 3 counted rows: B1 misses 2 of them -> 66.67 %, not 4 of 5.
    assert sample["B_1"]["Counts"] == 2 and sample["B_1"]["%_missing_values"] == pytest.approx(66.67)
    assert tables.overallMissingPercent == pytest.approx(3 / 12 * 100, abs=0.01)

    captured = []
    monkeypatch_target = completeness_tools
    original = monkeypatch_target._missing_value_plot_from_matrix

    def spy(matrix, **kwargs):
        captured.append(matrix)
        return original(matrix, **kwargs)

    monkeypatch_target._missing_value_plot_from_matrix = spy
    try:
        completeness_tools.completeness_missing_value_plot("protein")
    finally:
        monkeypatch_target._missing_value_plot_from_matrix = original
    assert captured[0].shape[0] == 3


def test_heatmap_uses_the_same_selection(loaded, monkeypatch):
    seen = []
    monkeypatch.setattr(completeness_tools, "_to_png_bytes", lambda fig, plt, **kw: b"png")

    class Sns:
        @staticmethod
        def heatmap(frame, **kwargs):
            seen.append(frame)
            return kwargs["ax"]

    monkeypatch.setattr(completeness_tools, "_get_sns", lambda: Sns)
    assert completeness_tools.completeness_missing_value_heatmap("protein") == b"png"
    assert seen[0].shape[0] == 3


def test_count_is_zero_when_every_row_has_a_value(monkeypatch):
    frame = _frame().iloc[:3]
    meta = pd.DataFrame({"sample": SAMPLES, "condition": ["A", "A", "B", "B"]})
    monkeypatch.setattr(completeness_tools, "_frame_and_meta", lambda kind: (frame, meta))
    assert completeness_tools.completeness_tables("protein").excludedAllMissingCount == 0
    assert completeness_tools.completeness_excluded_feature_count("protein") == 0
    assert report_function._completeness_exclusion_html("protein") == ""


def test_report_states_the_exclusion(loaded):
    html = report_function._completeness_exclusion_html("protein")
    assert "2 features were excluded because they have no value in any selected sample" in html


def test_report_is_silent_when_no_annotation(monkeypatch):
    def boom(kind):
        raise ValueError("no annotation")

    monkeypatch.setattr(completeness_tools, "_frame_and_meta", boom)
    assert report_function._completeness_exclusion_html("protein") == ""
