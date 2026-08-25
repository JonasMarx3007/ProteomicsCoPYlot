from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from app.services.functions import impute_values_with_diagnostics, qqnorm_plot_data


SAMPLES = ["s1", "s2", "s3"]


def _imputation_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "s1": [10.0, np.nan, 12.0, np.nan, 14.0, 15.0],
            "s2": [11.0, 12.0, np.nan, 14.0, np.nan, 16.0],
            "s3": [np.nan, 13.0, 14.0, 15.0, 16.0, np.nan],
        }
    )


def _imputed_values(seed: int) -> np.ndarray:
    result = impute_values_with_diagnostics(
        _imputation_frame(),
        SAMPLES,
        seed=seed,
        sample_wise=True,
    )
    return result.imputed_data[SAMPLES].to_numpy(dtype=float)


def test_same_seed_reproduces_values_and_different_seed_changes_draws() -> None:
    first = _imputed_values(1234)
    repeated = _imputed_values(1234)
    different = _imputed_values(1235)

    np.testing.assert_array_equal(first, repeated)
    assert not np.array_equal(first, different)


def test_imputation_does_not_mutate_numpy_global_rng() -> None:
    np.random.seed(20260805)
    expected = np.random.random(8)

    np.random.seed(20260805)
    _imputed_values(17)
    observed = np.random.random(8)

    np.testing.assert_array_equal(observed, expected)


def test_concurrent_seeded_imputations_are_session_independent() -> None:
    seeds = [7, 11, 7, 19, 11, 7, 19, 11] * 4
    expected = {seed: _imputed_values(seed) for seed in set(seeds)}

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_imputed_values, seeds))

    for seed, result in zip(seeds, results):
        np.testing.assert_array_equal(result, expected[seed])


def test_qq_subsampling_is_seeded_and_does_not_touch_global_rng() -> None:
    values = np.linspace(1.0, 200_000.0, 200_000)
    np.random.seed(99)
    expected_global = np.random.random(4)

    np.random.seed(99)
    first = qqnorm_plot_data(values, max_points=1_000, seed=23)
    repeated = qqnorm_plot_data(values, max_points=1_000, seed=23)
    different = qqnorm_plot_data(values, max_points=1_000, seed=24)
    observed_global = np.random.random(4)

    assert first == repeated
    assert first != different
    np.testing.assert_array_equal(observed_global, expected_global)
