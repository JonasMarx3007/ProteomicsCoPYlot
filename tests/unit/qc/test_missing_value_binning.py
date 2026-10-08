"""The missing-value plot never counts features identified in no sample.

Split out of test_small_bugs.py (2026-10-02)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

from app.services.completeness_tools import (
    _missing_value_plot_from_matrix,
)



def _missing_matrix() -> pd.DataFrame:
    rng = np.random.default_rng(4)
    values = pd.DataFrame(rng.normal(20, 2, (400, 8)), columns=[f"s{i}" for i in range(8)])
    holes = rng.integers(0, 9, 400)
    for row, count in enumerate(holes):
        if count:
            values.iloc[row, :count] = np.nan
    return values


def _plot_counts(matrix: pd.DataFrame, bin_count: int) -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    png = _missing_value_plot_from_matrix(
        matrix,
        title_label="Protein",
        bin_count=bin_count,
        header=False,
        text=False,
        text_size=8,
        color="#2563eb",
        width_cm=10,
        height_cm=6,
        dpi=72,
    )
    plt.close("all")
    assert png[:4] == b"\x89PNG"
    na = matrix.isna().sum(axis=1)
    return int((na != matrix.shape[1]).sum())


def test_never_identified_features_are_excluded_regardless_of_binning() -> None:
    matrix = _missing_matrix()
    all_missing = int((matrix.isna().sum(axis=1) == matrix.shape[1]).sum())
    assert all_missing > 0, "fixture must contain never-identified features"
    assert _plot_counts(matrix, 0) == _plot_counts(matrix, 3) == len(matrix) - all_missing


def test_missing_value_plot_renders_under_both_binning_modes() -> None:
    matrix = _missing_matrix()
    for bin_count in (0, 3, 5):
        assert _plot_counts(matrix, bin_count) > 0
