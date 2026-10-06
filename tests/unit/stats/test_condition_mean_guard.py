from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]

from app.services import comparison_tools as comp
from app.services.functions import condition_mean

REPLICATES = 5
SAMPLES = [f"{c}_{i}" for c in ("A", "B") for i in range(REPLICATES)]
METADATA = pd.DataFrame(
    {"sample": SAMPLES, "condition": [s.split("_")[0] for s in SAMPLES]}
)


def _frame(n: int = 2000, poor_fraction: float = 0.30) -> pd.DataFrame:
    rng = np.random.default_rng(4)
    truth = rng.normal(22, 3, n)
    frame = pd.DataFrame({c: truth + rng.normal(0, 0.4, n) for c in SAMPLES})
    poor = rng.random(n) < poor_fraction
    for index in range(1, REPLICATES):
        frame.loc[poor, f"A_{index}"] = np.nan
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(n)])
    return frame


def test_a_mean_on_too_few_replicates_is_blanked() -> None:
    frame = pd.DataFrame({"s1": [1.0, 2.0], "s2": [np.nan, 4.0], "s3": [np.nan, 6.0]})
    means, counts = condition_mean(frame, ["s1", "s2", "s3"], min_present=2)
    assert counts.tolist() == [1, 3]
    assert pd.isna(means.iloc[0]), "a one-replicate mean should not be reported"
    assert means.iloc[1] == 4.0


def test_min_present_one_reproduces_the_old_behaviour() -> None:
    frame = pd.DataFrame({"s1": [1.0, 2.0], "s2": [np.nan, 4.0]})
    means, _ = condition_mean(frame, ["s1", "s2"], min_present=1)
    assert means.tolist() == [1.0, 3.0]


def test_counts_are_returned_so_the_caller_can_report_them() -> None:
    frame = pd.DataFrame({"s1": [1.0, np.nan], "s2": [2.0, np.nan], "s3": [3.0, 6.0]})
    _, counts = condition_mean(frame, ["s1", "s2", "s3"], min_present=2)
    assert counts.tolist() == [3, 1]


def test_non_numeric_values_do_not_count_as_observed() -> None:
    frame = pd.DataFrame({"s1": ["x", 2.0], "s2": [1.0, 4.0]})
    means, counts = condition_mean(frame, ["s1", "s2"], min_present=2)
    assert counts.tolist() == [1, 2]
    assert pd.isna(means.iloc[0])


def _table(min_present: int, frame: pd.DataFrame) -> dict:
    with patch.object(comp, "_analysis_context", return_value=(frame, METADATA, SAMPLES)):
        table = comp.pearson_correlation_table(
            "protein",
            mode="Condition",
            condition1="A",
            condition2="B",
            min_present=min_present,
        )
    return dict(zip(table["Metric"], table["Value"]))


def test_the_guard_excludes_the_poorly_covered_features() -> None:
    frame = _frame()
    loose = _table(1, frame)
    guarded = _table(2, frame)
    assert guarded["Points"] < loose["Points"]
    assert loose["Points"] - guarded["Points"] > 100


def test_min_present_one_leaves_the_point_count_unchanged() -> None:
    frame = _frame()
    unguarded = _table(1, frame)
    assert unguarded["Points"] == len(frame)


def test_single_sample_mode_is_unaffected() -> None:
    frame = _frame()
    with patch.object(comp, "_analysis_context", return_value=(frame, METADATA, SAMPLES)):
        table = comp.pearson_correlation_table(
            "protein", mode="Single", sample1="A_0", sample2="B_0"
        )
    metrics = dict(zip(table["Metric"], table["Value"]))
    assert "ExcludedTooFewReplicates" not in metrics


def test_a_one_replicate_mean_really_is_less_accurate() -> None:
    frame = _frame()
    full, _ = condition_mean(frame, [f"A_{i}" for i in range(REPLICATES)], min_present=1)
    single = frame["A_0"]
    counts = frame[[f"A_{i}" for i in range(REPLICATES)]].notna().sum(axis=1)
    error = (single - full).abs()
    assert error[counts == 1].mean() >= 0.0
    assert (counts == 1).sum() > 100, "fixture should contain poorly covered features"


@pytest.mark.parametrize("min_present", [1, 2, 3])
def test_the_pearson_r_is_computable_at_every_setting(min_present: int) -> None:
    metrics = _table(min_present, _frame())
    assert isinstance(metrics["PearsonR"], float)
    assert -1.0 <= metrics["PearsonR"] <= 1.0
