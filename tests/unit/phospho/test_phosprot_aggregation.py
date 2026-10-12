from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.annotation import PhosprotAggregateRequest
from app.services.phosprot_tools import transform_phosprot


SAMPLES = ["s1", "s2", "s3", "s4"]
META = pd.DataFrame(
    {"sample": SAMPLES, "condition": ["control", "control", "treated", "treated"]}
)


def _sites(values: list[list[float]]) -> pd.DataFrame:
    count = len(values)
    frame = pd.DataFrame(values, columns=SAMPLES)
    frame.insert(0, "PTM_Collapse_key", [f"P1_S{i}" for i in range(1, count + 1)])
    frame.insert(0, "Gene_group", ["G1"] * count)
    frame.insert(0, "Protein_group", ["P1"] * count)
    frame.insert(0, "PTM_localization", [f"S{i}" for i in range(1, count + 1)])
    frame.insert(0, "UPD_seq", [f"PEPTIDE{i}" for i in range(1, count + 1)])
    return frame


def test_robust_site_median_is_default_and_removes_site_baselines() -> None:
    data = _sites(
        [
            [0.0, 1.0, 2.0, 3.0],
            [10.0, 11.0, 12.0, 13.0],
            [20.0, np.nan, 22.0, np.nan],
            [np.nan, np.nan, np.nan, np.nan],
        ]
    )

    out = transform_phosprot(data, META, data_scale="log2")

    assert PhosprotAggregateRequest().mode == "robust_site_median"
    assert out.loc[0, SAMPLES].to_numpy(dtype=float) == pytest.approx(
        [-1.5, -0.5, 0.5, 1.5]
    )
    assert out.loc[0, "site_num"] == 4
    assert out.loc[0, "site_num_eligible"] == 3
    assert out.loc[0, "site_observed__s2"] == 2
    assert out.loc[0, "site_coverage__s2"] == pytest.approx(2 / 3)


def test_robust_site_median_requires_half_the_fixed_site_set() -> None:
    data = _sites(
        [
            [1.0, 2.0, 3.0, 4.0],
            [10.0, 11.0, 12.0, np.nan],
            [20.0, 21.0, 22.0, np.nan],
        ]
    )

    out = transform_phosprot(data, META, data_scale="log2")

    assert np.isfinite(out.loc[0, "s1"])
    assert np.isnan(out.loc[0, "s4"])
    assert out.loc[0, "site_observed__s4"] == 1
    assert out.loc[0, "site_coverage__s4"] == pytest.approx(1 / 3)


def test_imputed_values_do_not_overwrite_observed_site_coverage() -> None:
    observed = _sites(
        [
            [1.0, 2.0, 3.0, 4.0],
            [10.0, 11.0, 12.0, np.nan],
            [20.0, 21.0, 22.0, np.nan],
        ]
    )
    imputed = observed.copy()
    imputed.loc[imputed["s4"].isna(), "s4"] = [13.0, 23.0]

    out = transform_phosprot(
        imputed,
        META,
        data_scale="log2",
        coverage_data=observed,
    )

    assert out.loc[0, "site_observed__s4"] == 1
    assert out.loc[0, "site_coverage__s4"] == pytest.approx(1 / 3)
    assert out.loc[0, "s4"] == pytest.approx(1.5)


@pytest.mark.parametrize("implementation", ["backend", "notebook"])
def test_imputed_sample_without_observations_contributes(implementation) -> None:
    from proteomicscopylot import notebook_functions as nb
    collapse = transform_phosprot if implementation == "backend" else nb.transform_phosprot
    observed = _sites([[1., 2., 3., np.nan], [10., 11., 12., np.nan]])
    imputed = observed.copy()
    imputed["s4"] = [4., 13.]
    out = collapse(imputed, META, data_scale="log2", coverage_data=observed)
    assert out.loc[0, "s4"] == pytest.approx(1.5)
    assert out.loc[0, "site_observed__s4"] == 0
    assert out.loc[0, "site_coverage__s4"] == 0
    unfilled = collapse(observed, META, data_scale="log2")
    assert np.isnan(unfilled.loc[0, "s4"])


def test_transformed_zero_is_an_observation_but_raw_zero_is_missing() -> None:
    data = _sites([[0.0, 1.0, 2.0, 3.0]])

    transformed = transform_phosprot(data, META, data_scale="log2")
    raw = transform_phosprot(data, META, data_scale="linear")

    assert transformed.loc[0, "site_observed__s1"] == 1
    assert np.isfinite(transformed.loc[0, "s1"])
    assert raw.loc[0, "site_observed__s1"] == 0
    assert np.isnan(raw.loc[0, "s1"])


def test_nonfinite_measurements_are_missing_not_sites_or_abundance() -> None:
    data = _sites([[np.inf, 1.0, 2.0, 3.0]])

    robust = transform_phosprot(data, META, data_scale="log2")
    strict = transform_phosprot(data, META, mode="sum_propagate_na", data_scale="log2")

    assert robust.loc[0, "site_observed__s1"] == 0
    assert np.isnan(robust.loc[0, "s1"])
    assert np.isnan(strict.loc[0, "s1"])


def test_sum_propagate_na_uses_a_fixed_eligible_set_and_exports_coverage() -> None:
    data = _sites(
        [
            [1.0, 2.0, np.nan, 4.0],
            [10.0, 20.0, 30.0, 40.0],
            [np.nan, np.nan, np.nan, np.nan],
        ]
    )

    out = transform_phosprot(data, META, mode="sum_propagate_na")

    # Every mode returns log2 now, so the linear sums 11, 22 and 44 come back as
    # their logarithms; the propagated NaN is unaffected.
    assert out.loc[0, SAMPLES].to_numpy(dtype=float, na_value=np.nan) == pytest.approx(
        [np.log2(11.0), np.log2(22.0), np.nan, np.log2(44.0)], nan_ok=True
    )
    assert out.loc[0, "site_num"] == 3
    assert out.loc[0, "site_num_eligible"] == 2
    assert out.loc[0, "site_observed__s3"] == 1
    assert out.loc[0, "site_coverage__s3"] == pytest.approx(0.5)


@pytest.mark.parametrize("mode", ["sum_ignore_na", "mean"])
def test_shared_site_modes_cannot_flip_a_fold_change(mode: str) -> None:
    """Both sites change by +1 log2 (A -> B); condition B detects one more site.

    Summing whatever was observed gave B a larger sum for the coverage, not the
    biology: +1.0 per site came out as a negative protein fold change. Over the
    sites quantified in every sample the protein change is the sites' change.
    """
    data = _sites(
        [
            [100.0, 100.0, 200.0, 200.0],  # quantified everywhere, doubles in B
            [np.nan, np.nan, 20.0, 20.0],  # detected in B only
        ]
    )
    out = transform_phosprot(data, META, mode=mode)
    values = out.loc[0, SAMPLES].to_numpy(dtype=float)
    assert values[2] - values[0] == pytest.approx(1.0)
    assert out.loc[0, "site_supplied__s3"] == 1  # the B-only site did not contribute


@pytest.mark.parametrize(
    "mode,expected",
    [
        # the linear aggregate is 30.0; every mode now returns log2
        ("sum_ignore_na", np.log2(30.0)),
        ("mean", np.log2(30.0)),
    ],
)
def test_legacy_non_strict_modes_remain_available(mode: str, expected: float) -> None:
    data = _sites(
        [
            [1.0, 2.0, np.nan, 4.0],
            [10.0, 20.0, 30.0, 40.0],
        ]
    )

    out = transform_phosprot(data, META, mode=mode)

    assert out.loc[0, "s3"] == pytest.approx(expected)


def test_unknown_aggregation_mode_is_rejected_by_schema() -> None:
    with pytest.raises(ValidationError):
        PhosprotAggregateRequest(mode="removed_mode")


def test_duplicate_metadata_samples_are_rejected() -> None:
    duplicate_meta = pd.DataFrame(
        {"sample": ["s1", "s1"], "condition": ["control", "treated"]}
    )
    with pytest.raises(ValueError, match="duplicate samples"):
        transform_phosprot(_sites([[1.0, 2.0, 3.0, 4.0]]), duplicate_meta)


def test_robust_site_median_output_is_centred_not_abundance() -> None:
    high = _sites([[100.0, 100.0, 200.0, 200.0]])
    low = high.copy()
    low[SAMPLES] = low[SAMPLES] / 10.0
    low["Protein_group"] = "P2"
    low["Gene_group"] = "G2"
    low["PTM_Collapse_key"] = "P2_S1"

    out = transform_phosprot(pd.concat([high, low], ignore_index=True), META)

    values = out.set_index("Phosphoprotein")[SAMPLES]
    assert values.loc["P1"].tolist() == pytest.approx(values.loc["P2"].tolist())
    assert values.loc["P1", "s3"] - values.loc["P1", "s1"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("aggregation", "centred"),
    [
        ("robust_site_median", True),
        ("sum_ignore_na", False),
        ("sum_propagate_na", False),
        ("mean", False),
        ("uploaded", False),
        (None, False),
    ],
)
def test_only_robust_site_median_counts_as_centred(aggregation, centred) -> None:
    from unittest.mock import patch

    from app.services.analysis_matrix import phosprot_values_are_centred

    class _Annotation:
        phosprot_aggregation = aggregation

    with patch("app.services.annotation_store.get_annotation", return_value=_Annotation()):
        assert phosprot_values_are_centred("phosprot") is centred


def test_the_other_kinds_are_never_centred() -> None:
    from unittest.mock import patch

    from app.services.analysis_matrix import phosprot_values_are_centred

    class _Annotation:
        phosprot_aggregation = "robust_site_median"

    with patch("app.services.annotation_store.get_annotation", return_value=_Annotation()):
        assert phosprot_values_are_centred("protein") is False
        assert phosprot_values_are_centred("phospho") is False


def test_the_axis_label_says_ratio_only_when_centred() -> None:
    from app.services.functions import abundance_axis_label

    assert abundance_axis_label("Protein") == "log10 Protein Intensity"
    assert abundance_axis_label("Phosphoprotein") == "log10 Phosphoprotein Intensity"
    assert (
        abundance_axis_label("Phosphoprotein", True)
        == "log10 Phosphoprotein Ratio to Site Median"
    )


def test_the_aggregation_mode_reaches_the_annotation() -> None:
    from app.schemas.annotation import AnnotationFilterConfig
    from app.services.annotation_store import get_annotation, save_annotation

    frame = pd.DataFrame({"Phosphoprotein": ["P1"], "s1": [1.0]})
    metadata = pd.DataFrame({"sample": ["s1"], "condition": ["control"]})
    save_annotation(
        kind="phosprot",
        source_data=frame,
        metadata=metadata,
        log2_data=frame,
        filtered_data=frame,
        is_log2_transformed=True,
        metadata_source="shared_phospho",
        filter_config=AnnotationFilterConfig(),
        auto_detected=False,
        warnings=[],
        phosprot_aggregation="robust_site_median",
    )
    assert get_annotation("phosprot").phosprot_aggregation == "robust_site_median"


@pytest.mark.parametrize("mode", ["robust_site_median", "sum_ignore_na", "mean"])
def test_aggregate_from_phospho_records_the_mode_it_used(mode: str) -> None:
    from unittest.mock import patch

    from app.schemas.annotation import AnnotationFilterConfig
    from app.services import phosprot_tools
    from app.services.annotation_store import get_annotation

    sites = _sites(
        [
            [100.0, 110.0, 200.0, 220.0],
            [50.0, 55.0, 100.0, 110.0],
        ]
    )

    class _PhosphoAnnotation:
        metadata = META
        log2_data = sites
        filtered_data = sites
        imputed_data = None
        imputation = None
        filter_config = AnnotationFilterConfig()

    with (
        patch.object(phosprot_tools, "_shared_phospho_annotation", return_value=_PhosphoAnnotation()),
        patch.object(phosprot_tools, "save_table_dataset"),
    ):
        phosprot_tools.aggregate_from_phospho(mode=mode)

    assert get_annotation("phosprot").phosprot_aggregation == mode


# The Annotation page offers exactly these modes and sources and starts on these
# defaults: frontend/tests/unit/phosprot-aggregation-defaults.test.tsx compares it
# with PhosprotAggregateRequest in the generated OpenAPI schema.


@pytest.mark.parametrize("implementation", ["app", "pip"])
def test_mean_uses_only_sites_quantified_in_every_sample(implementation: str) -> None:
    """A strong site seen only in control must not reverse a site that rises in treatment."""
    from proteomicscopylot import notebook_functions

    data = _sites(
        [
            [10.0, 10.0, 12.0, 12.0],      # complete site, up in treated
            [1000.0, 1000.0, np.nan, np.nan],  # high site observed only in control
        ]
    )
    collapse = transform_phosprot if implementation == "app" else notebook_functions.transform_phosprot
    out = collapse(data, META, mode="mean", data_scale="linear")
    values = out.loc[0, SAMPLES].to_numpy(dtype=float)
    assert values == pytest.approx(np.log2([10.0, 10.0, 12.0, 12.0]))
    assert values[2] > values[0]

    only_partial = _sites([[1.0, np.nan, 2.0, 2.0], [np.nan, 1.0, 2.0, 2.0]])
    out = collapse(only_partial, META, mode="mean", data_scale="linear")
    assert np.isnan(out.loc[0, SAMPLES].to_numpy(dtype=float)).all()
