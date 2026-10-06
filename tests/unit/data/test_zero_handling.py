from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.stats import AnovaRequest, SimulationRequest
from app.services import stats_tools as st
from app.services.functions import (
    select_matrix,
    impute_values_with_diagnostics,
    log2_transform_data,
    raw_zero_to_nan,
    use_existing_log2_data,
)

SAMPLES = [f"{group}_{i}" for group in ("A", "B") for i in range(3)]
META = pd.DataFrame(
    {"sample": SAMPLES, "condition": [s.split("_")[0] for s in SAMPLES]}
)


def _frame(zero_measurement_at: int | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(1)
    frame = pd.DataFrame(rng.normal(20, 2, (60, len(SAMPLES))), columns=SAMPLES)
    frame.insert(0, "Phosphoprotein", [f"PP{i}" for i in range(60)])
    frame.insert(1, "Gene_group", [f"G{i}" for i in range(60)])
    frame["site_num"] = [0, 0, 0] + list(range(1, 58))
    frame["PTM_Collapse_keys"] = ["S1;S2"] * 60
    if zero_measurement_at is not None:
        frame.loc[zero_measurement_at, SAMPLES[0]] = 0.0
    return frame


def _volcano(frame: pd.DataFrame) -> pd.DataFrame:
    with patch.object(st, "_stats_source", return_value=("filtered", frame, META, [])):
        return st._volcano_dataframe(
            kind="phosprot",
            condition1="A",
            condition2="B",
            identifier="workflow",
            p_value_threshold=0.05,
            log2fc_threshold=1.0,
            test_type="unpaired",
            use_uncorrected=False,
            data_source="data",
        )[2]


def _anova(frame: pd.DataFrame) -> pd.DataFrame:
    with patch.object(st, "_stats_source", return_value=("filtered", frame, META, [])):
        return st._anova_dataframe(AnovaRequest(kind="phosprot", dataSource="data"))[2]


def _simulation(frame: pd.DataFrame) -> pd.DataFrame:
    with patch.object(st, "_stats_source", return_value=("filtered", frame, META, [])):
        return st._simulation_dataframe(
            SimulationRequest(
                kind="phosprot", condition1="A", condition2="B", dataSource="data"
            )
        )[2]


BUILDERS = {"volcano": _volcano, "anova": _anova, "simulation": _simulation}


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_zero_in_an_annotation_column_is_preserved(name: str) -> None:
    result = BUILDERS[name](_frame())
    assert (result["site_num"] == 0).sum() == 3, "annotation zeros were destroyed"
    assert result["site_num"].isna().sum() == 0


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_zero_in_a_transformed_measurement_is_preserved(name: str) -> None:
    with_zero = BUILDERS[name](_frame(zero_measurement_at=5))
    assert not with_zero.empty
    row = with_zero[with_zero["Phosphoprotein"] == "PP5"]
    assert not row.empty
    assert float(row[SAMPLES[0]].iloc[0]) == 0.0
    if "pval" in row:
        assert np.isfinite(float(row["pval"].iloc[0]))


@pytest.mark.parametrize("name", sorted(BUILDERS))
def test_string_annotation_columns_are_untouched(name: str) -> None:
    result = BUILDERS[name](_frame())
    assert result["PTM_Collapse_keys"].notna().all()
    assert result["Gene_group"].notna().all()


def test_raw_boundary_helper_only_touches_measurement_columns() -> None:
    frame = pd.DataFrame(
        {"s1": [0.0, 1.0], "s2": [2.0, 0.0], "site_num": [0, 3], "label": ["a", "b"]}
    )
    out = raw_zero_to_nan(frame, ["s1", "s2"])
    assert out["s1"].isna().tolist() == [True, False]
    assert out["s2"].isna().tolist() == [False, True]
    assert out["site_num"].tolist() == [0, 3], "annotation column was modified"
    assert out["label"].tolist() == ["a", "b"]


def test_raw_boundary_helper_tolerates_absent_columns() -> None:
    frame = pd.DataFrame({"s1": [0.0, 1.0]})
    out = raw_zero_to_nan(frame, ["s1", "not_present"])
    assert out["s1"].isna().tolist() == [True, False]


def test_raw_boundary_helper_does_not_mutate_its_input() -> None:
    frame = pd.DataFrame({"s1": [0.0, 1.0]})
    raw_zero_to_nan(frame, ["s1"])
    assert frame["s1"].tolist() == [0.0, 1.0]


def test_log2_boundary_converts_raw_zero_but_keeps_log2_zero() -> None:
    raw = pd.DataFrame({"s1": [0.0, 1.0, 2.0], "label": [0, 1, 2]})
    transformed = log2_transform_data(raw, ["s1"])
    assert transformed["s1"].isna().tolist() == [True, False, False]
    assert transformed.loc[1, "s1"] == 0.0
    assert transformed["label"].tolist() == [0, 1, 2]

    already_log2 = use_existing_log2_data(raw, ["s1"])
    assert already_log2["s1"].tolist() == [0.0, 1.0, 2.0]


def test_imputation_does_not_impute_a_transformed_zero() -> None:
    frame = pd.DataFrame({"s1": [0.0, np.nan, 2.0], "s2": [1.0, 2.0, 3.0]})
    result = impute_values_with_diagnostics(frame, ["s1", "s2"], seed=7)
    assert result.missing_before == 1
    assert result.imputed_data.loc[0, "s1"] == 0.0
    assert np.isfinite(result.imputed_data.loc[1, "s1"])


def test_there_is_no_raw_fallback_to_convert_zeros_in() -> None:
    """A level with no annotated matrix is an error, not a silent downgrade.

    `select_matrix` used to fall back to the raw uploaded frame when neither the
    log2 nor the filtered matrix existed, converting zeros to missing on the way
    so the numbers looked plausible. The analysis then ran on a matrix nobody
    chose, under the label of one they did. There is no fallback now: every
    source names one matrix and raises when it is absent.
    """
    raw = pd.DataFrame({"s1": [0.0, 1.0], "label": [0, 1]})
    metadata = pd.DataFrame({"sample": ["s1"], "condition": ["A"]})
    annotation = SimpleNamespace(
        metadata=metadata,
        filtered_data=pd.DataFrame(),
        log2_data=pd.DataFrame(),
        imputation=None,
        imputed_data=pd.DataFrame(),
        is_log2_transformed=False,
    )
    with (
        patch("app.services.data_tools._get_current_frame", return_value=raw),
        patch("app.services.annotation_store.get_annotation", return_value=annotation),
    ):
        for source in ("data", "filtered", "imputed"):
            with pytest.raises(ValueError) as error:
                select_matrix("protein", source)
            assert "not available" in str(error.value), source

    # With the annotated matrix present, "data" is that matrix and nothing else.
    annotation.log2_data = raw.copy()
    with (
        patch("app.services.data_tools._get_current_frame", return_value=raw),
        patch("app.services.annotation_store.get_annotation", return_value=annotation),
    ):
        source, selected, _ = select_matrix("protein", "data")
    assert source == "data"
    assert selected.loc[0, "s1"] == 0.0, "the annotated matrix is returned as stored"


def test_an_unknown_source_names_the_ones_that_exist() -> None:
    with pytest.raises(ValueError) as error:
        select_matrix("protein", "log2")
    message = str(error.value)
    assert "log2" in message
    assert "data, filtered, imputed" in message, "the message should list the vocabulary"


NON_FINITE_SAMPLES = ["WT_1", "WT_2", "WT_3", "KO_1", "KO_2", "KO_3"]


def _non_finite_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            [18.0, 18.1, -np.inf, 19.0, 19.1, 18.9],
            [17.5, 17.6, 17.4, 18.2, 18.3, 18.1],
        ],
        columns=NON_FINITE_SAMPLES,
    )
    frame.insert(0, "ProteinNames", ["P_INF", "P_OK"])
    return frame


def test_an_already_log2_upload_treats_non_finite_values_as_missing() -> None:
    out = use_existing_log2_data(_non_finite_frame(), NON_FINITE_SAMPLES)
    values = out.loc[0, NON_FINITE_SAMPLES].to_numpy(dtype=float)
    assert not np.isinf(values).any(), (
        "an -inf survived ingest; filter_data counts with notna(), so it would pass "
        "the completeness filter as a measurement and yield an infinite fold change"
    )
    assert np.isnan(values).sum() == 1


def test_a_non_finite_value_does_not_survive_the_completeness_filter() -> None:
    from app.services.functions import filter_data

    metadata = pd.DataFrame(
        {"sample": NON_FINITE_SAMPLES, "condition": ["WT"] * 3 + ["KO"] * 3}
    )
    ingested = use_existing_log2_data(_non_finite_frame(), NON_FINITE_SAMPLES)
    kept = set(filter_data(ingested, metadata, 3, "per_group")["ProteinNames"])
    assert "P_INF" not in kept
    assert "P_OK" in kept


def test_raw_ingest_coerces_infinities_alongside_zero() -> None:
    out = raw_zero_to_nan(pd.DataFrame({"a": [np.inf, -np.inf, 0.0, 5.0]}), ["a"])
    assert out["a"].isna().sum() == 3
    assert out["a"].dropna().tolist() == [5.0]

