from __future__ import annotations

import typing
import gzip
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.annotation import (
    AnnotationFilterConfig,
    NormalizationMethod,
)
from app.services import restore_state
from app.services.annotation_store import reset_all_annotations, save_annotation
from app.services.condition_palette_store import (
    get_condition_palette,
    reset_condition_palettes,
    set_condition_palette,
)
from app.services.dataset_store import (
    get_current_dataset,
    reset_all_datasets,
    save_peptide_path,
    save_table_dataset,
)
from app.services.peptide_metadata_store import (
    clear_peptide_metadata,
    get_peptide_metadata,
    save_peptide_metadata,
)
from app.services.restore_state import _coerce_filter_config


def test_every_filter_field_survives_a_round_trip() -> None:
    original = AnnotationFilterConfig(
        method="percentage",
        minPresent=2,
        minPercentage=80.0,
        mode="overall",
        normalization="vsn",
    )
    restored = _coerce_filter_config(original.model_dump())
    lost = [
        field
        for field, value in original.model_dump().items()
        if restored.model_dump().get(field) != value
    ]
    assert not lost, (
        f"restore silently dropped {lost}; add the field to _coerce_filter_config"
    )


@pytest.mark.parametrize("normalization", sorted(typing.get_args(NormalizationMethod)))
def test_every_normalization_method_round_trips(normalization: str) -> None:
    original = AnnotationFilterConfig(normalization=normalization)
    assert _coerce_filter_config(original.model_dump()).normalization == normalization


def test_unknown_normalization_falls_back_but_says_so() -> None:
    """Restoring is best-effort, but a coercion that changes the analysis must be said.

    Rewriting an unrecognised method to "none" re-runs everything unnormalized
    and the methods report then states "none" -- a reproducibility claim that is
    quietly false. Loading approximately is right; loading silently is not.
    """
    warnings: list[str] = []
    restored = _coerce_filter_config({"normalization": "loess"}, warnings)
    assert restored.normalization == "none"
    assert any("loess" in w and "not recognised" in w for w in warnings), warnings


def test_legacy_state_without_the_field_still_restores() -> None:
    legacy = {
        "method": "at_least_n",
        "minPresent": 3,
        "minPercentage": 70.0,
        "mode": "per_group",
    }
    warnings: list[str] = []
    restored = _coerce_filter_config(legacy, warnings)
    assert restored.normalization == "none"
    assert warnings == [], "a field that is simply absent is a legacy state file, not an error"
    assert restored.minPresent == 3
    assert restored.mode == "per_group"


@pytest.mark.parametrize(
    "payload,expected,reported",
    [
        ({"method": "nonsense"}, "at_least_n", True),
        ({"method": "percentage"}, "percentage", False),
    ],
)
def test_invalid_method_falls_back_and_is_reported(
    payload: dict, expected: str, reported: bool
) -> None:
    warnings: list[str] = []
    assert _coerce_filter_config(payload, warnings).method == expected
    assert bool(warnings) is reported, warnings


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"mode": "nonsense"}, "per_group"),
        ({"mode": "overall"}, "overall"),
    ],
)
def test_invalid_mode_falls_back(payload: dict, expected: str) -> None:
    assert _coerce_filter_config(payload).mode == expected


def test_out_of_range_numbers_are_clamped() -> None:
    restored = _coerce_filter_config({"minPresent": -5, "minPercentage": 500.0})
    assert restored.minPresent == 0
    assert restored.minPercentage == 100.0


def test_non_dict_payload_yields_defaults() -> None:
    for payload in (None, "", [], 42):
        restored = _coerce_filter_config(payload)
        assert restored.model_dump() == AnnotationFilterConfig().model_dump()


def _minimal_state(package_name: str = "Restored") -> dict:
    return {
        "format": "copylot_state_v1",
        "backend": {
            "activePackage": package_name,
            "packages": [
                {
                    "name": package_name,
                    "datasets": {
                        "protein": None,
                        "phospho": None,
                        "phosprot": None,
                        "peptide": None,
                    },
                }
            ],
        },
    }


def test_restore_rolls_back_live_state_after_unexpected_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_all_datasets()
    reset_condition_palettes()
    old_frame = pd.DataFrame({"Protein": ["P1"], "S1": [3.25]})
    save_table_dataset("old.tsv", "protein", old_frame)
    set_condition_palette("protein", {"control": "#123456"})

    def fail_after_clear(_package_name: str) -> str:
        raise RuntimeError("injected restore failure")

    monkeypatch.setattr(restore_state, "create_package", fail_after_clear)
    with pytest.raises(RuntimeError, match="injected restore failure"):
        restore_state.apply_restore_state(_minimal_state(), {})

    restored = get_current_dataset("protein")
    assert restored is not None
    pd.testing.assert_frame_equal(restored.frame, old_frame)
    assert get_condition_palette("protein") == {"control": "#123456"}


def test_current_export_keeps_peptide_metadata_for_every_package() -> None:
    reset_all_datasets()
    clear_peptide_metadata()
    try:
        for package_name, marker in (("One", "first"), ("Two", "second")):
            restore_state.create_package(package_name)
            save_peptide_metadata(
                f"{package_name}.csv",
                pd.DataFrame({"sample": [marker], "condition": ["control"]}),
                package_name=package_name,
            )

        payload = json.loads(gzip.decompress(restore_state.export_state_blob()).decode("utf-8"))
        packages = {entry["name"]: entry for entry in payload["backend"]["packages"]}
        assert packages["One"]["peptideMetadata"]["frame"]["data"][0][0] == "first"
        assert packages["Two"]["peptideMetadata"]["frame"]["data"][0][0] == "second"
        assert "peptideMetadata" not in payload["backend"]

        clear_peptide_metadata()
        restore_state.apply_restore_state(payload, {})
        assert get_peptide_metadata(package_name="One").frame.iloc[0, 0] == "first"
        assert get_peptide_metadata(package_name="Two").frame.iloc[0, 0] == "second"
    finally:
        reset_all_datasets()
        clear_peptide_metadata()


def test_current_export_preserves_every_annotation_filter_option() -> None:
    reset_all_annotations()
    reset_all_datasets()
    try:
        source = pd.DataFrame({"Protein": ["P1"], "S1": [3.25]})
        metadata = pd.DataFrame({"sample": ["S1"], "condition": ["control"]})
        save_table_dataset("protein.tsv", "protein", source)
        config = AnnotationFilterConfig(
            method="percentage",
            minPresent=1,
            minPercentage=85,
            mode="overall",
            normalization="vsn",
        )
        save_annotation(
            kind="protein",
            source_data=source,
            metadata=metadata,
            log2_data=source,
            filtered_data=source,
            is_log2_transformed=True,
            metadata_source="manual",
            filter_config=config,
            auto_detected=False,
            warnings=[],
        )

        payload = json.loads(gzip.decompress(restore_state.export_state_blob()).decode("utf-8"))
        annotations = payload["backend"]["packages"][0]["annotations"]
        assert annotations[0]["filter"] == config.model_dump()
    finally:
        reset_all_annotations()
        reset_all_datasets()


def test_portable_export_omits_all_local_dataset_paths() -> None:
    reset_all_datasets()
    try:
        source = pd.DataFrame({"Protein": ["P1"], "S1": [3.25]})
        local_table_path = r"C:\Users\Researcher\private\protein.tsv"
        local_peptide_path = r"D:\Lab Data\peptides.tsv"
        save_table_dataset(
            "protein.tsv",
            "protein",
            source,
            source_path=local_table_path,
        )
        save_peptide_path(local_peptide_path)

        portable_payload = json.loads(
            gzip.decompress(restore_state.export_state_blob(portable=True)).decode("utf-8")
        )
        regular_payload = json.loads(
            gzip.decompress(restore_state.export_state_blob()).decode("utf-8")
        )

        portable_datasets = portable_payload["backend"]["packages"][0]["datasets"]
        regular_datasets = regular_payload["backend"]["packages"][0]["datasets"]
        assert portable_payload["portable"] is True
        assert portable_datasets["protein"]["path"] is None
        assert portable_datasets["peptide"]["path"] is None
        assert local_table_path not in json.dumps(portable_payload)
        assert local_peptide_path not in json.dumps(portable_payload)
        assert regular_payload["portable"] is False
        assert regular_datasets["protein"]["path"] == local_table_path
        assert regular_datasets["peptide"]["path"] == local_peptide_path
    finally:
        reset_all_datasets()


@pytest.mark.parametrize(
    "mode", ["robust_site_median", "sum_ignore_na", "sum_propagate_na", "mean", "uploaded"]
)
def test_known_aggregation_modes_survive_restore(mode: str) -> None:
    from app.services.restore_state import _coerce_phosprot_aggregation

    assert _coerce_phosprot_aggregation(mode) == mode
    assert _coerce_phosprot_aggregation(mode.upper()) == mode
    assert _coerce_phosprot_aggregation(f"  {mode}  ") == mode


@pytest.mark.parametrize("payload", ["nonsense", "", None, 123, {"a": 1}, []])
def test_an_unknown_aggregation_in_a_state_file_is_dropped(payload) -> None:
    from app.services.restore_state import _coerce_phosprot_aggregation

    assert _coerce_phosprot_aggregation(payload) is None


def test_the_export_actually_carries_the_aggregation_mode() -> None:
    reset_all_annotations()
    reset_all_datasets()
    try:
        source = pd.DataFrame({"Phosphoprotein": ["P1"], "S1": [3.25]})
        metadata = pd.DataFrame({"sample": ["S1"], "condition": ["control"]})
        save_table_dataset("phosprot.tsv", "phosprot", source)
        save_annotation(
            kind="phosprot",
            source_data=source,
            metadata=metadata,
            log2_data=source,
            filtered_data=source,
            is_log2_transformed=True,
            metadata_source="shared_phospho",
            filter_config=AnnotationFilterConfig(),
            auto_detected=False,
            warnings=[],
            phosprot_aggregation="robust_site_median",
        )

        payload = json.loads(gzip.decompress(restore_state.export_state_blob()).decode("utf-8"))
        entries = [
            entry
            for package in payload["backend"]["packages"]
            for entry in package["annotations"]
            if entry.get("kind") == "phosprot"
        ]
        assert entries, "the phosprot annotation must appear in the state file"
        assert entries[0].get("phosprotAggregation") == "robust_site_median"
    finally:
        reset_all_annotations()
        reset_all_datasets()


def test_a_restored_robust_site_median_frame_is_still_recognised_as_centred() -> None:
    from unittest.mock import patch

    from app.services.functions import _phosprot_values_are_centred
    from app.services.restore_state import _coerce_phosprot_aggregation

    class _Annotation:
        phosprot_aggregation = _coerce_phosprot_aggregation("robust_site_median")

    with patch("app.services.annotation_store.get_annotation", return_value=_Annotation()):
        assert _phosprot_values_are_centred("phosprot") is True
