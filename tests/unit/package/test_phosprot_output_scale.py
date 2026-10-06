from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from proteomicscopylot.notebook_functions import transform_phosprot, volcano_data_f

SAMPLES = [f"Ctrl_{i}" for i in (1, 2, 3)] + [f"Treat_{i}" for i in (1, 2, 3)]
MODES = ["robust_site_median", "mean", "sum_ignore_na", "sum_propagate_na"]


def _meta() -> pd.DataFrame:
    return pd.DataFrame({"sample": SAMPLES, "condition": ["Ctrl"] * 3 + ["Treat"] * 3})


def _sites(n_proteins: int = 80, seed: int = 3) -> tuple[pd.DataFrame, dict[str, float]]:
    rng = np.random.default_rng(seed)
    rows, truth = [], {}
    for p in range(n_proteins):
        base = rng.lognormal(11, 1.0)
        effect = rng.normal(0, 1.0)
        truth[f"PROT{p}"] = effect
        for s in range(3):
            values = [base * rng.lognormal(0, 0.25) for _ in range(3)]
            values += [base * (2**effect) * rng.lognormal(0, 0.25) for _ in range(3)]
            rows.append(
                {
                    "UPD_seq": f"SEQ{p}_{s}",
                    "PTM_localization": "0.99",
                    "Protein_group": f"PROT{p}",
                    "Gene_group": f"G{p}",
                    "PTM_Collapse_key": f"K{p}_{s}",
                    **dict(zip(SAMPLES, values)),
                }
            )
    return pd.DataFrame(rows), truth


def _aggregate(mode: str) -> tuple[pd.DataFrame, dict[str, float]]:
    data, truth = _sites()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return transform_phosprot(data, _meta(), mode=mode, data_scale="linear"), truth


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_returns_log2_not_raw_intensity(mode: str) -> None:
    """Downstream labels the difference log2FC whichever mode produced it.

    The sum and mean modes aggregate original-scale intensities, so without a
    transform here their fold changes are differences of raw intensities -- in
    the thousands -- under a column headed log2FC.
    """
    values = _aggregate(mode)[0][SAMPLES].to_numpy(dtype=float)
    values = values[np.isfinite(values)]
    assert values.max() < 60, f"{mode} returned values up to {values.max():.0f}; log2 intensities are ~10-30"


@pytest.mark.parametrize("mode", MODES[:3])
def test_fold_changes_recover_the_simulated_effect(mode: str) -> None:
    aggregated, truth = _aggregate(mode)
    # `truth` is the treatment effect, Treat - Ctrl. log2FC is condition1 minus
    # condition2, so Treat is selected first for the two to line up.
    result = volcano_data_f(aggregated, _meta(), "Treat", "Ctrl", workflow="Phosphoprotein")
    key = next(c for c in ("Phosphoprotein", "ProteinNames", "Gene_group") if c in result.columns)
    expected = result[key].map(truth)
    usable = result["log2FC"].notna() & expected.notna()
    assert np.corrcoef(result.loc[usable, "log2FC"], expected[usable])[0, 1] > 0.9
    assert np.median(np.abs(result.loc[usable, "log2FC"] - expected[usable])) < 0.5
