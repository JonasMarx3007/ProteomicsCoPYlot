"""A control-corrected volcano names the test it ran.

With controls, "unpaired" (pooled Student's t) is computed as a Welch-type
test: four variance components, Satterthwaite degrees of freedom. The page
sends "unpaired_welch" for that case; a caller that sends "unpaired" got the
same arithmetic under the wrong name in the notebook settings and the
assistant evidence. `effective_test_type` makes every caller record the test
that ran, and the arithmetic is unchanged.
"""
from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from app.services import stats_tools as st
from app.services.functions import effective_test_type

SAMPLES = [f"{group}{i}" for group in ("A", "B", "CA", "CB") for i in range(3)]
META = pd.DataFrame({"sample": SAMPLES, "condition": [s.rstrip("0123456789") for s in SAMPLES]})


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(5)
    frame = pd.DataFrame(rng.normal(20, 1, (40, len(SAMPLES))), columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(40)])
    return frame


@pytest.mark.parametrize("test_type,with_controls,expected", [
    ("unpaired", True, "unpaired_welch"),
    ("unpaired", False, "unpaired"),
    ("unpaired_welch", True, "unpaired_welch"),
    ("paired", True, "paired"),
])
def test_only_unpaired_with_controls_is_renamed(test_type, with_controls, expected) -> None:
    assert effective_test_type(test_type, with_controls=with_controls) == expected


def test_unpaired_and_welch_give_the_same_control_corrected_numbers() -> None:
    frame = _frame()
    results = {}
    for test_type in ("unpaired", "unpaired_welch"):
        with patch.object(st, "_stats_source", return_value=("filtered", frame, META, [])):
            results[test_type] = st._volcano_dataframe(
                kind="protein", condition1="A", condition2="B", identifier="workflow",
                p_value_threshold=0.05, log2fc_threshold=1, test_type=test_type, use_uncorrected=False,
                data_source="data", condition1_control="CA", condition2_control="CB",
            )[2]
    pd.testing.assert_frame_equal(results["unpaired"], results["unpaired_welch"])


def test_without_controls_the_two_tests_still_differ() -> None:
    frame = _frame()
    frame.loc[:, ["B0", "B1", "B2"]] *= 1.3  # unequal variances
    results = {}
    for test_type in ("unpaired", "unpaired_welch"):
        with patch.object(st, "_stats_source", return_value=("filtered", frame, META, [])):
            results[test_type] = st._volcano_dataframe(
                kind="protein", condition1="A", condition2="B", identifier="workflow",
                p_value_threshold=0.05, log2fc_threshold=1, test_type=test_type, use_uncorrected=False,
                data_source="data",
            )[2]
    assert not np.allclose(results["unpaired"]["pval"], results["unpaired_welch"]["pval"])


def test_the_assistant_evidence_names_welch_for_a_control_volcano(monkeypatch) -> None:
    from app.schemas.analysis import AnalysisVolcanoResponse
    from app.services import analysis_functions
    from app.services.scientific_assistant import _canvas_tile_evidence

    def calculate(payload):
        return AnalysisVolcanoResponse(kind="protein", source="volcano_control", labelColumn="ProteinNames",
            totalRows=1, upregulatedCount=1, downregulatedCount=0, notSignificantCount=0,
            points=[dict(label="P1", selectionLabel="P1", significance="Upregulated", log2FC=2, negLog10P=3)])

    monkeypatch.setattr(analysis_functions, "analysis_volcano_data", calculate)
    settings = dict(kind="protein", source="volcano_control", condition1="A", condition2="B",
                    condition1Control="CA", condition2Control="CB", useUncorrected=False, testType="unpaired")
    evidence = _canvas_tile_evidence({"tileEvidence": [{"type": "volcanoControl", "settings": settings}]}, "extended")[0]
    assert "volcano_testing|selected_test=unpaired_welch" in evidence.text
    assert "satterthwaite" in evidence.text
