from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import stats_tools as st
from app.services.functions import constant_within_group

REPLICATES = 3
SAMPLES = [f"{c}_{i}" for c in ("A", "B") for i in range(REPLICATES)]
METADATA = pd.DataFrame(
    {"sample": SAMPLES, "condition": [s.split("_")[0] for s in SAMPLES]}
)
FLOOR_ROWS = range(1900, 1912)


def _frame(n: int = 2000) -> pd.DataFrame:
    rng = np.random.default_rng(17)
    base = rng.normal(22, 2, n)
    frame = pd.DataFrame({c: base + rng.normal(0, 0.45, n) for c in SAMPLES})
    frame.iloc[:150, REPLICATES:] += 2.0
    for index in FLOOR_ROWS:
        frame.iloc[index, :REPLICATES] = 14.00
        frame.iloc[index, REPLICATES:] = 14.05
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(n)])
    return frame


def _volcano(frame: pd.DataFrame) -> pd.DataFrame:
    with patch.object(st, "_stats_source", return_value=("filtered", frame, METADATA, [])):
        return st._volcano_dataframe(
            kind="protein",
            condition1="A",
            condition2="B",
            identifier="workflow",
            p_value_threshold=0.05,
            log2fc_threshold=1.0,
            test_type="unpaired",
            use_uncorrected=False,
            data_source="data",
        )[2]


def test_identical_values_are_detected_whatever_their_binary_representation() -> None:
    values = np.array([
        [14.0, 14.0, 14.0],
        [14.05, 14.05, 14.05],
        [0.1 + 0.2, 0.1 + 0.2, 0.1 + 0.2],
        [14.0, 14.0, 14.1],
        [20.1, 20.4, 19.8],
    ])
    assert constant_within_group(values).tolist() == [True, True, True, False, False]
    variances = np.nanvar(values, axis=1, ddof=1)
    assert variances[1] != 0.0, "the fixture must keep its non-representable case"


def test_missing_values_do_not_make_a_group_look_constant() -> None:
    values = np.array([[14.0, np.nan, 14.0], [14.0, np.nan, 15.0]])
    assert constant_within_group(values).tolist() == [True, False]


def test_a_row_with_no_observations_is_not_flagged() -> None:
    values = np.array([[np.nan, np.nan, np.nan]])
    assert constant_within_group(values).tolist() == [False]


def test_the_floor_rows_are_flagged_and_nothing_else_is() -> None:
    result = _volcano(_frame())
    flagged = set(result.loc[result["zero_variance"], "ProteinNames"])
    assert flagged == {f"P{i}" for i in FLOOR_ROWS}


def test_genuine_effects_are_not_flagged() -> None:
    result = _volcano(_frame())
    genuine = result[result["ProteinNames"].isin([f"P{i}" for i in range(150)])]
    assert int(genuine["zero_variance"].sum()) == 0


def test_the_flagged_rows_really_do_dominate_the_ranking() -> None:
    result = _volcano(_frame())
    top = result.nsmallest(12, "adj_pval")
    assert top["zero_variance"].all(), "the top of the volcano should be the floor rows"
    assert abs(top["log2FC"]).max() < 0.1, "and their fold changes should be negligible"


def test_the_flag_does_not_change_any_p_value() -> None:
    result = _volcano(_frame())
    flagged = result[result["zero_variance"]]
    from scipy.stats import ttest_ind

    expected = ttest_ind(
        np.full(REPLICATES, 14.00), np.full(REPLICATES, 14.05), equal_var=True
    ).pvalue
    assert np.allclose(flagged["pval"].to_numpy(), expected, rtol=1e-6) or (
        flagged["pval"].max() < 1e-40
    ), "the p-value should be whatever the plain t-test gives, unchanged"


def test_flagged_rows_can_still_fail_the_fold_change_threshold() -> None:
    result = _volcano(_frame())
    flagged = result[result["zero_variance"]]
    assert (flagged["significance"] == "Not significant").all()


@pytest.mark.parametrize("column", ["pval", "adj_pval", "log2FC", "significance"])
def test_existing_columns_are_untouched(column: str) -> None:
    result = _volcano(_frame())
    assert column in result.columns
    assert result[column].notna().all()
