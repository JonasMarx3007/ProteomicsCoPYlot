"""Three ways a restored project could silently differ from the saved one.

1. An imputation record that no longer validates used to take the imputed
   matrix down with it, with no warning, so every "imputed data" plot fell
   back to the raw matrix. The matrix is now kept and the loss of its
   parameters is reported.
2. A dataset re-read from its saved absolute path was trusted blindly. The
   export now records size and SHA-256 of the file; a restore that finds a
   different file at the same path says so.
3. A table derived inside the tool (a phosprot aggregation) had no file of its
   own and was left out of portable exports, so restoring one asked for a
   replacement file the user never had. The table now travels in the export.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi import UploadFile

from app.schemas.annotation import AnnotationFilterConfig, AnnotationImputationInfo
from app.services import restore_state
from app.services.annotation_store import get_annotation, reset_all_annotations, save_annotation
from app.services.dataset_store import get_current_dataset, reset_all_datasets, save_table_dataset


@pytest.fixture(autouse=True)
def clean_stores():
    reset_all_annotations()
    reset_all_datasets()
    yield
    reset_all_annotations()
    reset_all_datasets()


def _export() -> dict:
    return json.loads(gzip.decompress(restore_state.export_state_blob()).decode("utf-8"))


def _export_portable() -> dict:
    return json.loads(gzip.decompress(restore_state.export_state_blob(portable=True)).decode("utf-8"))


def _source() -> pd.DataFrame:
    return pd.DataFrame({"ProteinNames": ["P1", "P2"], "S1": [10.0, 11.0], "S2": [10.5, float("nan")]})


def _metadata() -> pd.DataFrame:
    return pd.DataFrame({"sample": ["S1", "S2"], "condition": ["a", "b"]})


def _save_protein(tmp_path: Path, *, with_imputation: bool) -> Path:
    source = _source()
    path = tmp_path / "protein.tsv"
    source.to_csv(path, sep="\t", index=False)
    save_table_dataset("protein.tsv", "protein", source, source_path=str(path))
    imputed = source.copy()
    imputed.loc[1, "S2"] = 9.0
    save_annotation(
        kind="protein",
        source_data=source,
        metadata=_metadata(),
        log2_data=source,
        filtered_data=source,
        is_log2_transformed=True,
        metadata_source="manual",
        filter_config=AnnotationFilterConfig(),
        auto_detected=False,
        warnings=[],
        imputation=AnnotationImputationInfo(mode="numerical", applied=True, seed=1) if with_imputation else None,
        imputed_data=imputed if with_imputation else None,
    )
    return path


# --- 1. imputation record ---------------------------------------------------


def test_an_unreadable_imputation_record_keeps_the_matrix_and_warns(tmp_path):
    _save_protein(tmp_path, with_imputation=True)
    state = _export()
    entry = state["backend"]["packages"][0]["annotations"][0]
    assert entry["imputedFrame"] is not None
    entry["imputation"] = {"mode": "numerical", "applied": True, "seed": -5}  # fails validation (seed >= 0)

    reset_all_annotations()
    reset_all_datasets()
    result = restore_state.apply_restore_state(state, {})
    warnings = " ".join(result.warnings)
    assert "imputation record" in warnings and "imputed matrix was kept" in warnings

    annotation = get_annotation("protein")
    assert annotation is not None
    assert not annotation.imputed_data.empty
    assert annotation.imputation is not None and annotation.imputation.applied is True
    assert annotation.imputation.mode == "unknown"


def test_a_missing_record_still_means_no_imputation(tmp_path):
    _save_protein(tmp_path, with_imputation=False)
    state = _export()
    entry = state["backend"]["packages"][0]["annotations"][0]
    assert entry["imputation"] is None and entry["imputedFrame"] is None
    reset_all_annotations()
    reset_all_datasets()
    result = restore_state.apply_restore_state(state, {})
    assert not any("imputation record" in w for w in result.warnings)
    assert get_annotation("protein").imputation is None


# --- 2. file fingerprint ----------------------------------------------------


def test_the_export_fingerprints_each_dataset_file(tmp_path):
    path = _save_protein(tmp_path, with_imputation=False)
    entry = _export()["backend"]["packages"][0]["datasets"]["protein"]
    assert entry["path"] == str(path)
    assert entry["sizeBytes"] == path.stat().st_size
    assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_portable_exports_keep_identity_without_disclosing_paths(tmp_path):
    path = _save_protein(tmp_path, with_imputation=True)
    entry = _export_portable()["backend"]["packages"][0]["datasets"]["protein"]
    assert entry["path"] is None
    assert entry["sizeBytes"] == path.stat().st_size
    assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("portable", [False, True])
@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("allow_local_paths", [False, True])
def test_replacement_integrity_preserves_only_matching_imputation(tmp_path, portable, changed, allow_local_paths):
    path = _save_protein(tmp_path, with_imputation=True)
    state = _export_portable() if portable else _export()
    package = state["backend"]["packages"][0]["name"]
    # Keep the original path present: an explicit replacement must win over it.
    content = path.read_bytes()
    if changed:
        content = content.replace(b"10.0", b"99.0")  # same size, different intensities
    replacement = restore_state.ReplacementInput(file=UploadFile(filename="replacement.tsv", file=io.BytesIO(content)))
    result = restore_state.apply_restore_state(state, {(package, "protein"): replacement}, allow_local_paths=allow_local_paths)
    annotation = get_annotation("protein")
    assert get_current_dataset("protein").frame.loc[0, "S1"] == (99.0 if changed else 10.0)
    assert annotation.imputation.applied is (not changed)
    assert annotation.imputed_data.empty is changed
    assert any("Discarded stale imputed data" in w for w in result.warnings) is changed
    if not changed:
        assert annotation.imputed_data.loc[1, "S2"] == 9.0


def test_unverifiable_replacement_cannot_reuse_imputation(tmp_path):
    path = _save_protein(tmp_path, with_imputation=True)
    state = _export_portable()
    package = state["backend"]["packages"][0]
    package["datasets"]["protein"].pop("sha256")
    replacement = restore_state.ReplacementInput(file=UploadFile(filename="protein.tsv", file=io.BytesIO(path.read_bytes())))
    result = restore_state.apply_restore_state(state, {(package["name"], "protein"): replacement}, allow_local_paths=False)
    assert get_annotation("protein").imputed_data.empty
    assert not get_annotation("protein").imputation.applied
    assert any("identity could not be verified" in w for w in result.warnings)


@pytest.mark.parametrize("portable,upload", [(False, False), (False, True), (True, True)])
def test_source_changed_before_saving_cannot_inherit_old_imputation(tmp_path, portable, upload):
    path = _save_protein(tmp_path, with_imputation=True)
    changed = _source()
    changed.loc[0, "S1"] = 99.0
    changed.to_csv(path, sep="\t", index=False)
    state = _export_portable() if portable else _export()
    package = state["backend"]["packages"][0]
    entry = package["datasets"]["protein"]
    assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert entry["tableSha256"] == restore_state._table_fingerprint(_source())
    replacements = {}
    if upload:
        replacements[(package["name"], "protein")] = restore_state.ReplacementInput(
            file=UploadFile(filename="protein.tsv", file=io.BytesIO(path.read_bytes()))
        )
    reset_all_annotations()
    reset_all_datasets()
    result = restore_state.apply_restore_state(state, replacements, allow_local_paths=not portable)
    annotation = get_annotation("protein")
    assert annotation.log2_data.loc[0, "S1"] == 99.0
    assert annotation.imputed_data.empty
    assert not annotation.imputation.applied
    assert any("differs from the data loaded" in warning for warning in result.warnings)
    assert any("Discarded stale imputed data" in warning for warning in result.warnings)


def test_loaded_table_fingerprint_ignores_index_and_numeric_dtype_but_not_values():
    frame = pd.DataFrame({"ProteinNames": ["α", "β"], "S1": [1, 2]})
    equivalent = frame.astype({"S1": float}).set_axis([10, 20])
    original = frame.copy(deep=True)
    assert restore_state._table_fingerprint(frame) == restore_state._table_fingerprint(equivalent)
    equivalent.loc[10, "S1"] = 1.0000000000000002
    assert restore_state._table_fingerprint(frame) != restore_state._table_fingerprint(equivalent)
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("value", ["typo", "12", -1, True, float("inf"), []])
def test_malformed_saved_fingerprint_is_reported_not_an_internal_error(tmp_path, value):
    path = _save_protein(tmp_path, with_imputation=False)
    assert "could not be verified" in restore_state._fingerprint_mismatch({"sizeBytes": value}, path)


def test_a_file_overwritten_after_export_is_restored_with_a_warning(tmp_path):
    path = _save_protein(tmp_path, with_imputation=False)
    state = _export()
    # A new search exported under the same name: same shape, different numbers.
    changed = _source()
    changed.loc[0, "S1"] = 99.0
    changed.to_csv(path, sep="\t", index=False)

    reset_all_annotations()
    reset_all_datasets()
    result = restore_state.apply_restore_state(state, {})
    assert any("was modified after this state was saved" in w and "protein.tsv" in w for w in result.warnings)
    assert float(get_current_dataset("protein").frame.loc[0, "S1"]) == 99.0  # restored anyway


def test_an_untouched_file_restores_without_a_warning(tmp_path):
    _save_protein(tmp_path, with_imputation=False)
    state = _export()
    reset_all_annotations()
    reset_all_datasets()
    result = restore_state.apply_restore_state(state, {})
    assert not any("modified after" in w for w in result.warnings)


@pytest.mark.parametrize("changed", [False, True])
def test_saved_imputation_is_only_retained_when_the_fingerprinted_source_matches(tmp_path, changed):
    path = _save_protein(tmp_path, with_imputation=True)
    state = _export()
    if changed:
        frame = _source()
        frame.loc[0, "S1"] = 99.0
        frame.to_csv(path, sep="\t", index=False)
    reset_all_annotations()
    reset_all_datasets()
    result = restore_state.apply_restore_state(state, {})
    annotation = get_annotation("protein")
    assert annotation.imputation.applied is (not changed)
    assert annotation.imputed_data.empty is changed
    assert any("Discarded stale imputed data" in w for w in result.warnings) is changed
    assert annotation.log2_data.loc[0, "S1"] == (99.0 if changed else 10.0)


def test_old_exports_without_a_fingerprint_are_not_checked(tmp_path):
    path = _save_protein(tmp_path, with_imputation=False)
    state = _export()
    entry = state["backend"]["packages"][0]["datasets"]["protein"]
    del entry["sizeBytes"], entry["sha256"]
    path.write_text(path.read_text() + "\n")
    reset_all_annotations()
    reset_all_datasets()
    result = restore_state.apply_restore_state(state, {})
    assert not any("modified after" in w for w in result.warnings)


# --- 3. derived tables travel in the export ---------------------------------


def _save_derived_phosprot() -> pd.DataFrame:
    frame = pd.DataFrame({"Phosphoprotein": ["P1"], "S1": [0.5], "S2": [-0.5]})
    save_table_dataset("phosprot_derived.tsv", "phosprot", frame, phosprot_aggregation="robust_site_median")
    return frame


def test_a_derived_table_is_embedded_in_both_export_flavours():
    frame = _save_derived_phosprot()
    for payload in (_export(), _export_portable()):
        entry = payload["backend"]["packages"][0]["datasets"]["phosprot"]
        assert entry["derived"] is True
        assert entry["frame"]["columns"] == list(frame.columns)
        assert entry["frame"]["data"] == [["P1", 0.5, -0.5]]
    assert _export_portable()["backend"]["packages"][0]["datasets"]["phosprot"]["path"] is None


def test_a_portable_restore_of_a_derived_table_needs_no_replacement_file():
    _save_derived_phosprot()
    state = _export_portable()
    reset_all_datasets()
    assert restore_state.inspect_missing_files(state, {}, allow_local_paths=False) == []
    result = restore_state.apply_restore_state(state, {}, allow_local_paths=False)
    restored = get_current_dataset("phosprot")
    assert restored is not None
    assert restored.frame.to_dict(orient="list") == {"Phosphoprotein": ["P1"], "S1": [0.5], "S2": [-0.5]}
    assert restored.phosprot_aggregation == "robust_site_median"
    assert any(name.endswith(":phosprot") for name in result.restored_datasets)


def test_an_uploaded_table_is_not_embedded(tmp_path):
    _save_protein(tmp_path, with_imputation=False)
    entry = _export()["backend"]["packages"][0]["datasets"]["protein"]
    assert "frame" not in entry and "derived" not in entry


def test_an_upload_that_only_has_a_temp_copy_is_still_not_derived(tmp_path, monkeypatch):
    """Uploads without a client path are copied into table_uploads; that is a
    file the user has, not a table the tool computed."""
    from app.api import routes_datasets

    upload_dir = tmp_path / "table_uploads"
    upload_dir.mkdir()
    copy = upload_dir / "abc_protein.tsv"
    _source().to_csv(copy, sep="\t", index=False)
    save_table_dataset("protein.tsv", "protein", _source(), source_path=str(copy))
    entry = _export()["backend"]["packages"][0]["datasets"]["protein"]
    assert "frame" not in entry and entry["path"] == str(copy)
    assert routes_datasets._table_upload_dir().name == "table_uploads"
    assert restore_state._table_backup_dir().name == "table_derived"
