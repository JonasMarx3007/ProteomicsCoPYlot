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
from app.services.functions import (
    paired_test_enabled,
    resolve_test_type,
    squeeze_variance,
    trigamma_inverse,
    variance_model,
)

UNPAIRED_MODELS = ["unpaired", "unpaired_welch", "unpaired_moderated"]


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
        ("unpaired_moderated", (False, "moderated")),
        ("paired_moderated", (True, "moderated")),
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


def test_trigamma_inverse_inverts_trigamma() -> None:
    from scipy.special import polygamma

    targets = np.array([0.05, 0.2, 1.0, 5.0, 50.0])
    recovered = polygamma(1, trigamma_inverse(targets))
    assert np.allclose(recovered, targets, rtol=1e-8)


def test_squeezed_variance_lies_between_observation_and_prior() -> None:
    rng = np.random.default_rng(3)
    dof = np.full(2000, 4.0)
    true_variance = 0.09 * rng.chisquare(6, 2000) / 6
    variances = true_variance * rng.chisquare(dof) / dof
    posterior, prior, df_prior = squeeze_variance(variances, dof)
    assert np.isfinite(df_prior) and df_prior > 0
    assert prior > 0
    low = np.minimum(variances, prior)
    high = np.maximum(variances, prior)
    assert np.all(posterior >= low - 1e-12)
    assert np.all(posterior <= high + 1e-12)
    assert posterior.std() < variances.std()


def test_homogeneous_variance_collapses_onto_the_prior() -> None:
    rng = np.random.default_rng(3)
    dof = np.full(2000, 4.0)
    variances = 0.09 * rng.chisquare(dof) / dof
    posterior, prior, df_prior = squeeze_variance(variances, dof)
    assert not np.isfinite(df_prior)
    assert np.allclose(posterior, prior)


def test_squeezed_variance_handles_degenerate_input() -> None:
    posterior, prior, df_prior = squeeze_variance(np.array([0.5]), np.array([4.0]))
    assert np.isfinite(posterior).all() and prior > 0
    posterior, _, _ = squeeze_variance(np.array([]), np.array([]))
    assert posterior.size == 0


@pytest.mark.parametrize("test_type", UNPAIRED_MODELS)
def test_all_variance_models_are_calibrated_under_the_null(test_type: str) -> None:
    frame, meta = _dataset(n_features=4000, n=4, seed=11)
    result = _volcano(frame, meta, test_type)
    false_positive_rate = float((result["pval"] < 0.05).mean())
    assert 0.02 < false_positive_rate < 0.08, f"{test_type}: {false_positive_rate:.1%}"


def test_moderated_recovers_power_at_three_replicates() -> None:
    frame, meta = _dataset(n_features=4000, n=3, n_true=400, effect=1.0, seed=23)
    truth = np.zeros(4000, bool)
    truth[:400] = True
    from statsmodels.stats.multitest import multipletests

    found = {}
    for test_type in ("unpaired", "unpaired_moderated"):
        result = _volcano(frame, meta, test_type)
        index = result["ProteinNames"].str.slice(1).astype(int).to_numpy()
        selected = multipletests(result["pval"], method="fdr_bh")[1] < 0.05
        true_positives = int(truth[index][selected].sum())
        false_positives = int((~truth[index][selected]).sum())
        found[test_type] = (true_positives, false_positives, int(selected.sum()))

    pooled_tp = found["unpaired"][0]
    moderated_tp, moderated_fp, moderated_hits = found["unpaired_moderated"]
    assert moderated_tp > pooled_tp * 5, f"expected a large power gain, got {found}"
    assert moderated_fp / max(1, moderated_hits) < 0.10


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


def test_paired_moderated_runs_and_stays_calibrated() -> None:
    rng = np.random.default_rng(31)
    n = 4
    columns = [f"{g}_{i}" for g in ("A", "B") for i in range(n)]
    meta = pd.DataFrame(
        {
            "sample": columns,
            "condition": [c.split("_")[0] for c in columns],
            "pair_id": [f"subject{i}" for i in range(n)] * 2,
        }
    )
    subject = rng.normal(0, 2, (3000, n))
    values = np.concatenate(
        [20 + subject + rng.normal(0, 0.3, (3000, n)), 20 + subject + rng.normal(0, 0.3, (3000, n))],
        axis=1,
    )
    frame = pd.DataFrame(values, columns=columns)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(3000)])
    frame.insert(1, "GeneNames", [f"G{i}" for i in range(3000)])
    rate = float((_volcano(frame, meta, "paired_moderated")["pval"] < 0.05).mean())
    assert 0.02 < rate < 0.09, f"paired moderated should stay near nominal, got {rate:.1%}"


def test_variance_models_agree_on_the_fold_change() -> None:
    frame, meta = _dataset(n_features=800, n=4, n_true=100, effect=1.0, seed=13)
    reference = _volcano(frame, meta, "unpaired")["log2FC"].to_numpy()
    for test_type in ("unpaired_welch", "unpaired_moderated"):
        other = _volcano(frame, meta, test_type)["log2FC"].to_numpy()
        assert np.allclose(reference, other, atol=1e-12)


def _heterogeneous_variances(seed: int = 5, features: int = 800, residual_dof: float = 4.0):
    rng = np.random.default_rng(seed)
    true_variance = 0.4 * (6.0 / rng.chisquare(6.0, features))
    observed = true_variance * rng.chisquare(residual_dof, features) / residual_dof
    return observed, np.full(features, residual_dof)


def test_the_fixture_produces_a_finite_prior_not_the_degenerate_one() -> None:
    from app.services.functions import _fit_variance_prior

    variances, dof = _heterogeneous_variances()
    _, df_prior = _fit_variance_prior(variances, dof)
    assert np.isfinite(df_prior), "the fixture lost its heterogeneity"
    assert 1.0 < df_prior < 100.0, df_prior


def test_shrinkage_actually_moves_the_variances() -> None:
    from app.services.functions import squeeze_variance

    variances, dof = _heterogeneous_variances()
    posterior, _, df_prior = squeeze_variance(variances, dof)
    moved = np.mean(np.abs(posterior - variances) / variances)
    assert moved > 0.10, f"posterior barely differs from raw variance ({moved:.3%})"


def test_the_posterior_lies_between_the_raw_variance_and_the_prior() -> None:
    from app.services.functions import _fit_variance_prior, squeeze_variance

    variances, dof = _heterogeneous_variances()
    var_prior, _ = _fit_variance_prior(variances, dof)
    posterior, _, _ = squeeze_variance(variances, dof)

    lower = np.minimum(variances, var_prior)
    upper = np.maximum(variances, var_prior)
    assert np.all(posterior >= lower - 1e-12)
    assert np.all(posterior <= upper + 1e-12)


def test_the_fitted_prior_matches_an_independent_computation() -> None:
    from scipy.special import polygamma

    from app.services.functions import _fit_variance_prior, trigamma_inverse

    variances, dof = _heterogeneous_variances()
    var_prior, df_prior = _fit_variance_prior(variances, dof)

    log_variance = np.log(variances)
    residual = dof / 2.0
    z = log_variance - (np.log(variances.mean()) if False else 0.0)
    observed_spread = np.var(log_variance, ddof=1)
    excess = observed_spread - float(np.mean(polygamma(1, residual)))
    expected_df_prior = float(2.0 * trigamma_inverse(np.array([excess]))[0])

    assert np.isfinite(expected_df_prior), "the reference computation degenerated"
    assert df_prior == pytest.approx(expected_df_prior, rel=1e-6), (
        f"prior degrees of freedom {df_prior:.4f} do not match the fitFDist "
        f"solution {expected_df_prior:.4f} for the same variances"
    )


def test_the_posterior_is_the_weighted_average_the_prior_implies() -> None:
    from app.services.functions import _fit_variance_prior, squeeze_variance

    variances, dof = _heterogeneous_variances()
    var_prior, df_prior = _fit_variance_prior(variances, dof)
    posterior, _, _ = squeeze_variance(variances, dof)

    weight = df_prior / (df_prior + dof)
    expected = weight * var_prior + (1.0 - weight) * variances
    assert np.allclose(posterior, expected, rtol=1e-9)
