"""Asking for one comparison returns exactly that comparison, unchanged.

Every post-hoc comparison costs one studentized-range integral per significant
feature, and that integral is the entire cost of the request: on a real project,
three pairs over 1,477 significant features took 25 s, of which 26 s of measured
`scipy.stats.studentized_range.sf` time. Asking for one pair is three times
cheaper.

The saving is only legitimate if the number does not depend on which other pairs
were computed alongside it -- and it does not: Tukey's `q` takes `k` from the
whole design and the MSE is pooled across every condition, neither of which the
selection touches. This file holds that claim to the only standard that matters:
the same pair, computed alone and computed with the others, must be identical.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services.functions import anova_posthoc_data

REPS = 4
CONDITIONS = ("A", "B", "C", "D")


@pytest.fixture(scope="module")
def dataset():
    """Four conditions, one of them shifted, so the ANOVA finds something."""
    rng = np.random.default_rng(20260916)
    samples = [f"{condition}_{index}" for condition in CONDITIONS for index in range(REPS)]
    frame = pd.DataFrame(rng.normal(20, 1.0, (150, len(samples))), columns=samples)
    frame.iloc[:60, -REPS:] += 3.0
    frame.insert(0, "ProteinNames", [f"P{index}" for index in range(150)])
    # A missing value, so the Tukey-Kramer unequal-n path is exercised too.
    frame.iloc[3, 1] = np.nan
    frame["adj_pval"] = 0.001
    metadata = pd.DataFrame(
        {"sample": samples, "condition": [c for c in CONDITIONS for _ in range(REPS)]}
    )
    return frame, metadata


def _pair_rows(frame: pd.DataFrame, left: str, right: str) -> pd.DataFrame:
    mask = (frame["group1"] == left) & (frame["group2"] == right)
    return frame[mask].sort_values("ProteinNames").reset_index(drop=True)


@pytest.fixture(scope="module")
def all_pairs(dataset):
    frame, metadata = dataset
    return anova_posthoc_data(frame.copy(), metadata.copy(), label_col="ProteinNames")


# --- the claim the saving rests on --------------------------------------------


@pytest.mark.parametrize("left,right", [("A", "B"), ("B", "C"), ("A", "D")])
def test_one_pair_alone_equals_that_pair_among_all_of_them(dataset, all_pairs, left, right) -> None:
    frame, metadata = dataset
    alone = anova_posthoc_data(frame, metadata, label_col="ProteinNames", pair=(left, right))

    expected = _pair_rows(all_pairs, left, right)
    actual = _pair_rows(alone, left, right)
    assert not expected.empty and len(actual) == len(expected)

    for column in ("q_statistic", "tukey_pval", "log2FC"):
        np.testing.assert_array_equal(
            actual[column].to_numpy(), expected[column].to_numpy(),
            err_msg=f"{column} changed when {left} vs {right} was computed alone",
        )
    assert actual["significance"].tolist() == expected["significance"].tolist()
    assert actual["n_group1"].tolist() == expected["n_group1"].tolist()


def test_only_the_asked_for_comparison_comes_back(dataset, all_pairs) -> None:
    frame, metadata = dataset
    alone = anova_posthoc_data(frame, metadata, label_col="ProteinNames", pair=("A", "C"))
    assert set(alone["comparison"]) == {"A vs C"}
    assert len(set(all_pairs["comparison"])) == 6, "four conditions make six pairs"
    assert len(alone) * 6 == len(all_pairs), "and one pair is a sixth of the work"


def test_asking_for_nothing_still_returns_every_pair(all_pairs) -> None:
    """The old behaviour, which the API keeps when no pair is named."""
    assert len(set(all_pairs["comparison"])) == 6


# --- the order is the user's, like every other comparison in the tool ---------


def test_the_condition_named_first_is_the_minuend(dataset) -> None:
    """The volcano convention. Reversing the pair flips the sign, nothing else."""
    frame, metadata = dataset
    forward = anova_posthoc_data(frame, metadata, label_col="ProteinNames", pair=("A", "D"))
    reverse = anova_posthoc_data(frame, metadata, label_col="ProteinNames", pair=("D", "A"))

    forward = forward.sort_values("ProteinNames").reset_index(drop=True)
    reverse = reverse.sort_values("ProteinNames").reset_index(drop=True)

    assert set(forward["comparison"]) == {"A vs D"}
    assert set(reverse["comparison"]) == {"D vs A"}
    np.testing.assert_array_equal(
        forward["log2FC"].to_numpy(), -reverse["log2FC"].to_numpy()
    )
    np.testing.assert_array_equal(
        forward["tukey_pval"].to_numpy(), reverse["tukey_pval"].to_numpy(),
    ), "the Tukey p-value is symmetric: q uses |difference|"


def test_a_pair_picked_backwards_still_matches_the_full_run(dataset, all_pairs) -> None:
    """Only the sign and the label differ from the canonical orientation."""
    frame, metadata = dataset
    every = _pair_rows(all_pairs, "A", "D")
    reverse = (
        anova_posthoc_data(frame, metadata, label_col="ProteinNames", pair=("D", "A"))
        .sort_values("ProteinNames")
        .reset_index(drop=True)
    )
    np.testing.assert_array_equal(reverse["tukey_pval"].to_numpy(), every["tukey_pval"].to_numpy())
    np.testing.assert_array_equal(reverse["log2FC"].to_numpy(), -every["log2FC"].to_numpy())


# --- refusals ------------------------------------------------------------------


def test_a_condition_that_is_not_there_is_named(dataset) -> None:
    frame, metadata = dataset
    with pytest.raises(ValueError, match="not present"):
        anova_posthoc_data(frame, metadata, label_col="ProteinNames", pair=("A", "Z"))


def test_one_condition_twice_is_refused(dataset) -> None:
    """Rather than silently comparing a group with itself."""
    frame, metadata = dataset
    with pytest.raises(ValueError, match="two different conditions"):
        anova_posthoc_data(frame, metadata, label_col="ProteinNames", pair=("B", "B"))


def test_two_conditions_still_produce_nothing(dataset) -> None:
    """With two groups the omnibus F and the one pair test the same hypothesis."""
    frame, metadata = dataset
    two = metadata[metadata["condition"].isin(["A", "B"])]
    assert anova_posthoc_data(frame, two, label_col="ProteinNames", pair=("A", "B")).empty
