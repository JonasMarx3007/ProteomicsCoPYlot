from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]

from app.services import stats_tools as st
from app.services.functions import resolve_test_type
# The legacy `paired="Paired"/"Unpaired"` argument lives only in the notebook packages.
from proteomicscopylot.notebook_functions import paired_test_enabled, variance_model

UNPAIRED_MODELS = ["unpaired", "unpaired_welch"]


def _dataset(n_features=1500, n=3, n_true=0, effect=0.0, seed=7):
    rng = np.random.default_rng(seed)
    columns = [f"{group}_{index}" for group in ("A", "B") for index in range(n)]
    meta = pd.DataFrame(
        {"sample": columns, "condition": [c.split("_")[0] for c in columns]}
    )
    sigma = np.sqrt(0.09 * rng.chisquare(6, n_features) / 6)[:, None]
    values = rng.normal(20, 2, (n_features, 1)) + rng.normal(0, 1, (n_features, 2 * n)) * sigma
    if n_true:
        values[:n_true, n:] += effect
    frame = pd.DataFrame(values, columns=columns)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(n_features)])
    frame.insert(1, "GeneNames", [f"G{i}" for i in range(n_features)])
    return frame, meta


def _volcano(frame, meta, test_type, log2fc_threshold=0.0):
    with patch.object(st, "_stats_source", return_value=("filtered", frame, meta, [])):
        return st._volcano_dataframe(
            kind="protein",
            condition1="A",
            condition2="B",
            identifier="workflow",
            p_value_threshold=0.05,
            log2fc_threshold=log2fc_threshold,
            test_type=test_type,
            use_uncorrected=True,
            data_source="data",
        )[2]


def test_legacy_test_types_keep_their_original_meaning() -> None:
    assert resolve_test_type("unpaired") == (False, "pooled")
    assert resolve_test_type("paired") == (True, "pooled")
    assert paired_test_enabled("unpaired") is False
    assert paired_test_enabled("paired") is True


@pytest.mark.parametrize(
    "value,expected",
    [
        ("unpaired_welch", (False, "welch")),
        ("  UNPAIRED_WELCH  ", (False, "welch")),
    ],
)
def test_new_test_types_resolve(value: str, expected: tuple[bool, str]) -> None:
    assert resolve_test_type(value) == expected


def test_unknown_test_type_is_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_test_type("wilcoxon")
    with pytest.raises(ValueError):
        variance_model("")


@pytest.mark.parametrize("test_type", UNPAIRED_MODELS)
def test_all_variance_models_are_calibrated_under_the_null(test_type: str) -> None:
    frame, meta = _dataset(n_features=4000, n=4, seed=11)
    result = _volcano(frame, meta, test_type)
    false_positive_rate = float((result["pval"] < 0.05).mean())
    assert 0.02 < false_positive_rate < 0.08, f"{test_type}: {false_positive_rate:.1%}"


def test_welch_does_not_assume_equal_variance() -> None:
    rng = np.random.default_rng(5)
    n = 5
    columns = [f"{g}_{i}" for g in ("A", "B") for i in range(n)]
    meta = pd.DataFrame({"sample": columns, "condition": [c.split("_")[0] for c in columns]})
    values = np.concatenate(
        [rng.normal(20, 0.1, (4000, n)), rng.normal(20, 1.0, (4000, n))], axis=1
    )
    frame = pd.DataFrame(values, columns=columns)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(4000)])
    frame.insert(1, "GeneNames", [f"G{i}" for i in range(4000)])
    welch = float((_volcano(frame, meta, "unpaired_welch")["pval"] < 0.05).mean())
    assert 0.02 < welch < 0.08, f"Welch should stay near nominal, got {welch:.1%}"


def test_variance_models_agree_on_the_fold_change() -> None:
    frame, meta = _dataset(n_features=800, n=4, n_true=100, effect=1.0, seed=13)
    reference = _volcano(frame, meta, "unpaired")["log2FC"].to_numpy()
    for test_type in ("unpaired_welch",):
        other = _volcano(frame, meta, test_type)["log2FC"].to_numpy()
        assert np.allclose(reference, other, atol=1e-12)


