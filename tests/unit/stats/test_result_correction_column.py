from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.stats import AnovaRequest, SimulationRequest
from app.services import stats_tools as st
from app.services.stats_tools import (
    CORRECTION_BENJAMINI_HOCHBERG,
    CORRECTION_NONE,
)

CONDITIONS = ("A", "B", "C")


def _fixture(n_features: int = 200, replicates: int = 3):
    rng = np.random.default_rng(5)
    columns = [f"{c}_{i}" for c in CONDITIONS for i in range(replicates)]
    meta = pd.DataFrame(
        {"sample": columns, "condition": [c.split("_")[0] for c in columns]}
    )
    frame = pd.DataFrame(
        rng.normal(20, 2, (n_features, len(columns))), columns=columns
    )
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(n_features)])
    frame.insert(1, "GeneNames", [f"G{i}" for i in range(n_features)])
    return frame, meta


def _volcano(uncorrected: bool) -> pd.DataFrame:
    frame, meta = _fixture()
    with patch.object(st, "_stats_source", return_value=("filtered", frame, meta, [])):
        return st._volcano_dataframe(
            kind="protein",
            condition1="A",
            condition2="B",
            identifier="workflow",
            p_value_threshold=0.05,
            log2fc_threshold=1.0,
            test_type="unpaired",
            use_uncorrected=uncorrected,
            data_source="data",
        )[2]


def _anova(uncorrected: bool) -> pd.DataFrame:
    frame, meta = _fixture()
    payload = AnovaRequest(kind="protein", useUncorrected=uncorrected, dataSource="data")
    with patch.object(st, "_stats_source", return_value=("filtered", frame, meta, [])):
        return st._anova_dataframe(payload)[2]


def _simulation(uncorrected: bool) -> pd.DataFrame:
    frame, meta = _fixture()
    payload = SimulationRequest(
        kind="protein",
        condition1="A",
        condition2="B",
        useUncorrected=uncorrected,
        dataSource="data",
    )
    with patch.object(st, "_stats_source", return_value=("filtered", frame, meta, [])):
        return st._simulation_dataframe(payload)[2]


BUILDERS = {"volcano": _volcano, "anova": _anova, "simulation": _simulation}


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_corrected_results_say_benjamini_hochberg(name: str) -> None:
    table = BUILDERS[name](uncorrected=False)
    assert "correction" in table.columns, f"{name} table has no correction column"
    assert (table["correction"] == CORRECTION_BENJAMINI_HOCHBERG).all()


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_uncorrected_results_say_so(name: str) -> None:
    table = BUILDERS[name](uncorrected=True)
    assert (table["correction"] == CORRECTION_NONE).all()
    assert "uncorrected" in CORRECTION_NONE


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_uncorrected_selected_pval_is_the_raw_pvalue_and_adj_pval_stays_adjusted(name: str) -> None:
    """2026-09-30: `adj_pval` no longer holds raw p-values when uncorrected is on."""
    table = BUILDERS[name](uncorrected=True)
    assert np.allclose(table["selected_pval"].to_numpy(), table["pval"].to_numpy())
    assert not np.allclose(table["adj_pval"].to_numpy(), table["pval"].to_numpy())


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_correction_changes_adj_pval_when_applied(name: str) -> None:
    table = BUILDERS[name](uncorrected=False)
    assert not np.allclose(table["adj_pval"].to_numpy(), table["pval"].to_numpy())
    assert np.allclose(table["selected_pval"].to_numpy(), table["adj_pval"].to_numpy())


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_result_columns(name: str) -> None:
    table = BUILDERS[name](uncorrected=False)
    for column in ("pval", "adj_pval", "selected_pval", "significance", "neg_log10_selected_pval"):
        assert column in table.columns
    assert "neg_log10_adj_pval" not in table.columns


def test_the_two_labels_are_distinguishable() -> None:
    assert CORRECTION_BENJAMINI_HOCHBERG != CORRECTION_NONE
    assert CORRECTION_BENJAMINI_HOCHBERG.strip() and CORRECTION_NONE.strip()
