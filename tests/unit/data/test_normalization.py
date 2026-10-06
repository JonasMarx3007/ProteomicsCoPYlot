from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.annotation import (
    AnnotationFilterConfig,
    phosprot_filter_config,
)
from app.services import phosprot_tools
from app.services.annotation_processor import compute_annotation_from_metadata
from app.services.functions import normalize_data, use_existing_log2_data

SAMPLES = [f"s{i}" for i in range(6)]
OFFSETS = np.array([0.0, 1.2, -0.9, 0.6, -1.5, 0.3])


def _frame(seed: int = 17, n_features: int = 400, missing: float = 0.15) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    values = rng.normal(20.0, 2.0, (n_features, len(SAMPLES))) + OFFSETS
    frame = pd.DataFrame(values, columns=SAMPLES)
    frame = frame.mask(rng.random(frame.shape) < missing)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(n_features)])
    return frame


COMMON_MEDIAN_TOLERANCE = {"median": 1e-9, "quantile": 1e-3}


@pytest.mark.parametrize("method", ["none", "median", "quantile", "vsn"])
@pytest.mark.parametrize("log2_upload", [False, True])
def test_cv_and_abundance_use_the_normalized_qc_matrix(monkeypatch, method, log2_upload):
    """CV and abundance describe the same matrix as every other QC plot.

    They used to read the raw upload, so with normalization on they reported
    variance the pipeline had already removed while the boxplot beside them
    showed aligned medians. Now they are 2 ** the normalized, unfiltered,
    non-imputed log2 matrix: a scale choice, not a matrix choice.
    """
    from app.services import plot_images, table_functions
    from app.services.annotation_processor import prepare_normalized_log2_data

    columns = ["A1", "A2", "A3"]
    linear = pd.DataFrame({"ProteinNames": ["P1", "P2", "P3", "P4"],
                           "A1": [1., 2., 4., np.nan], "A2": [2., 4., 8., np.nan],
                           "A3": [4., 8., 16., np.nan]})
    uploaded = linear.copy()
    if log2_upload:
        uploaded[columns] = np.log2(uploaded[columns])
    meta = pd.DataFrame({"sample": columns, "condition": "A"})
    if method == "vsn":
        monkeypatch.setattr("app.services.r_vsn.vsn_normalize_linear", lambda data: data * 0 + 99)
    normalized = prepare_normalized_log2_data(uploaded, columns, log2_upload, method)
    annotation = SimpleNamespace(source_data=uploaded, metadata=meta,
        is_log2_transformed=log2_upload, log2_data=normalized,
        filtered_data=normalized.iloc[:1], imputed_data=normalized.fillna(50))
    expected = normalized.copy()
    expected[columns] = np.power(2.0, expected[columns].apply(pd.to_numeric, errors="coerce"))
    from app.services import data_tools

    # metadata_for_kind and the two QC frame accessors live in data_tools, so
    # the matrix is patched once, where both the plots and the tables read it.
    monkeypatch.setattr(data_tools, "get_annotation", lambda kind: annotation)
    monkeypatch.setattr(data_tools, "qc_matrix", lambda kind: (normalized.copy(), meta.copy()))
    monkeypatch.setattr(plot_images, "get_annotation", lambda kind: annotation)
    monkeypatch.setattr(plot_images, "_get_current_frame", lambda kind: annotation.imputed_data)
    for module in [plot_images, table_functions]:
        monkeypatch.setattr(module, "_get_sample_columns", lambda kind, frame: columns)
        pd.testing.assert_frame_equal(module.linear_qc_frame("protein"), expected)
    cv = table_functions.prepare_cov_df(table_functions.linear_qc_frame("protein")[columns], meta)
    expected_cv = table_functions.prepare_cov_df(expected[columns], meta)
    pd.testing.assert_frame_equal(cv, expected_cv)
    if method == "none":
        # With no normalization the QC matrix is the upload itself.
        pd.testing.assert_frame_equal(expected[columns], linear[columns])
    abundance, _, _, _ = plot_images._abundance_mean_intensities("protein")
    np.testing.assert_allclose(abundance.A, np.log10(expected[columns].mean(axis=1).dropna()))


def test_median_normalization_changes_the_cv_a_loading_offset_produced(monkeypatch):
    """The reason for the matrix choice: a 4x loading is not sample variance."""
    from app.services import table_functions
    from app.services.annotation_processor import prepare_normalized_log2_data

    rng = np.random.default_rng(3)
    columns = ["A1", "A2", "A3", "A4"]
    # Small replicate noise, so that the 4x loading offset dominates the CV.
    base = np.power(2.0, rng.normal(20, 0.15, (300, 4)))
    base[:, 3] *= 4.0
    uploaded = pd.DataFrame(base, columns=columns)
    uploaded.insert(0, "ProteinNames", [f"P{i}" for i in range(300)])
    meta = pd.DataFrame({"sample": columns, "condition": "A"})
    raw_cv = float(table_functions.prepare_cov_df(uploaded[columns], meta)["median"].iloc[0])
    normalized = prepare_normalized_log2_data(uploaded, columns, False, "median")
    from app.services import data_tools

    monkeypatch.setattr(data_tools, "qc_matrix", lambda kind: (normalized.copy(), meta.copy()))
    normalized_cv = table_functions.prepare_cov_df(
        table_functions.linear_qc_frame("protein")[columns], meta
    )["median"].iloc[0]
    assert normalized_cv < raw_cv / 2


@pytest.mark.requires_r()
def test_r_uploaded_intensity_qc_matches_python_reference():
    import subprocess
    from app.services.r_runtime import detect_r_runtime

    runtime = detect_r_runtime()
    script = r'''
      source("proteomicscopylot/notebook_functions.R")
      original <- data.frame(ProteinNames=c("P1","P2","P3"),
        A1=c(1,2,4), A2=c(2,4,8), A3=c(4,8,16))
      meta <- data.frame(sample=c("A1","A2","A3"),condition="A")
      uploaded <- original
      uploaded[meta$sample] <- log2(uploaded[meta$sample])
      org_data <- inverse_log2_transform_data(uploaded,meta)
      data <- normalize_data(uploaded,meta,"median")
      stopifnot(isTRUE(all.equal(org_data[meta$sample],original[meta$sample])))
      grDevices::pdf(NULL)
      trace("boxplot.default", where=asNamespace("graphics"), print=FALSE,
        tracer=quote(stopifnot(all(abs(unlist(x) - 65.46536707079771) < 1e-8))))
      cov_plot(org_data,meta,data_scale="linear")
      untrace("boxplot.default",where=asNamespace("graphics"))
      trace("points.default",where=asNamespace("graphics"),print=FALSE,
        tracer=quote(stopifnot(isTRUE(all.equal(as.numeric(y),sort(log10(c(7,14,28)/3),decreasing=TRUE))))))
      abundance_plot(org_data,meta,data_scale="linear",legend=FALSE)
      untrace("points.default",where=asNamespace("graphics"))
      grDevices::dev.off()
    '''
    result = subprocess.run([runtime["executable"], "-e", script], cwd=ROOT,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("method", ["median", "quantile"])
def test_normalization_removes_loading_offsets(method: str) -> None:
    frame = _frame()
    before = frame[SAMPLES].median().to_numpy()
    after = normalize_data(frame, SAMPLES, method)[SAMPLES].median().to_numpy()
    assert before.std() > 0.5, "fixture should carry a real loading offset"
    assert after.std() < COMMON_MEDIAN_TOLERANCE[method]
    assert after.std() < before.std() / 1000.0
    assert np.isfinite(after).all()


@pytest.mark.parametrize("method", ["none", "median", "quantile"])
def test_missing_values_are_neither_filled_nor_moved(method: str) -> None:
    frame = _frame()
    out = normalize_data(frame, SAMPLES, method)
    assert np.array_equal(frame[SAMPLES].isna().to_numpy(), out[SAMPLES].isna().to_numpy())
    assert list(out.columns) == list(frame.columns)
    assert len(out) == len(frame)


def test_none_is_an_exact_passthrough() -> None:
    frame = _frame()
    out = normalize_data(frame, SAMPLES, "none")
    pd.testing.assert_frame_equal(out, frame)


@pytest.mark.parametrize("method", ["median", "quantile"])
def test_non_sample_columns_are_untouched(method: str) -> None:
    frame = _frame()
    out = normalize_data(frame, SAMPLES, method)
    pd.testing.assert_series_equal(out["ProteinNames"], frame["ProteinNames"])


def test_median_centering_preserves_every_fold_change() -> None:
    frame = _frame()
    out = normalize_data(frame, SAMPLES, "median")
    before = frame["s1"] - frame["s0"]
    after = out["s1"] - out["s0"]
    shift = (after - before).dropna()
    assert shift.std() < 1e-12, "median centering must shift a sample, not distort it"


def test_quantile_gives_every_sample_the_same_distribution() -> None:
    frame = _frame(missing=0.0)
    out = normalize_data(frame, SAMPLES, "quantile")[SAMPLES]
    reference = np.sort(out[SAMPLES[0]].to_numpy())
    for column in SAMPLES[1:]:
        assert np.allclose(np.sort(out[column].to_numpy()), reference, atol=1e-9)


def test_normalization_is_deterministic() -> None:
    frame = _frame()
    for method in ("median", "quantile"):
        first = normalize_data(frame, SAMPLES, method)[SAMPLES].to_numpy()
        second = normalize_data(frame, SAMPLES, method)[SAMPLES].to_numpy()
        assert np.array_equal(np.nan_to_num(first), np.nan_to_num(second))


def test_unequal_missingness_between_samples_is_handled() -> None:
    rng = np.random.default_rng(5)
    values = rng.normal(20.0, 2.0, (500, len(SAMPLES))) + OFFSETS
    frame = pd.DataFrame(values, columns=SAMPLES)
    rates = [0.02, 0.05, 0.10, 0.20, 0.35, 0.55]
    for column, rate in zip(SAMPLES, rates):
        frame.loc[rng.random(len(frame)) < rate, column] = np.nan
    before = frame[SAMPLES].median().to_numpy()
    medians = normalize_data(frame, SAMPLES, "quantile")[SAMPLES].median().to_numpy()
    assert medians.std() < 1e-3
    assert medians.std() < before.std() / 1000.0


def test_single_observation_column_does_not_crash() -> None:
    frame = _frame(n_features=50, missing=0.0)
    frame.loc[1:, "s3"] = np.nan
    for method in ("median", "quantile"):
        out = normalize_data(frame, SAMPLES, method)
        assert np.isfinite(out.loc[0, "s3"])


def test_all_missing_column_does_not_crash() -> None:
    frame = _frame(n_features=50, missing=0.0)
    frame["s2"] = np.nan
    for method in ("median", "quantile"):
        out = normalize_data(frame, SAMPLES, method)
        assert out["s2"].isna().all()


def test_unknown_method_is_rejected() -> None:
    frame = _frame(n_features=20)
    with pytest.raises(ValueError):
        normalize_data(frame, SAMPLES, "loess")


@pytest.mark.parametrize("method", ["median", "quantile"])
def test_a_metadata_frame_is_accepted_like_every_other_function(method: str) -> None:
    frame = _frame(n_features=200, missing=0.0)
    metadata = pd.DataFrame({"sample": SAMPLES, "condition": ["a"] * 3 + ["b"] * 3})
    from_meta = normalize_data(frame.copy(), metadata, method)[SAMPLES].to_numpy()
    from_list = normalize_data(frame.copy(), SAMPLES, method)[SAMPLES].to_numpy()
    assert np.allclose(from_meta, from_list, equal_nan=True), (
        "normalize_data must accept a metadata frame; it is the only public function "
        "whose second argument is not one, and passing meta used to return the input "
        "unchanged with no error"
    )


def test_unresolvable_sample_columns_raise_rather_than_returning_the_input() -> None:
    frame = _frame(n_features=20)
    with pytest.raises(ValueError, match="nothing would be normalized"):
        normalize_data(frame, ["not_a_column"], "median")


def test_a_partial_column_match_raises() -> None:
    frame = _frame(n_features=20)
    with pytest.raises(ValueError, match="not in the data"):
        normalize_data(frame, SAMPLES + ["not_a_column"], "median")


def test_metadata_without_a_sample_column_says_so() -> None:
    frame = _frame(n_features=20)
    with pytest.raises(ValueError, match="'sample' column"):
        normalize_data(frame, pd.DataFrame({"run": SAMPLES}), "median")


def test_requesting_no_normalization_is_still_a_no_op() -> None:
    frame = _frame(n_features=20)
    pd.testing.assert_frame_equal(normalize_data(frame, ["not_a_column"], "none"), frame)


@pytest.mark.parametrize("method", ["median", "quantile"])
def test_uploaded_metadata_applies_normalization_before_filtering(method: str) -> None:
    frame = _frame(n_features=100, missing=0.0)
    metadata = pd.DataFrame(
        {
            "sample": SAMPLES,
            "condition": ["control"] * 3 + ["treated"] * 3,
        }
    )

    result = compute_annotation_from_metadata(
        data=frame,
        metadata=metadata,
        is_log2_transformed=True,
        min_present=0,
        filter_mode="per_group",
        normalization=method,
    )
    expected = normalize_data(use_existing_log2_data(frame, SAMPLES), SAMPLES, method)

    pd.testing.assert_frame_equal(result.log2_data, expected)
    pd.testing.assert_frame_equal(result.filtered_data, expected)
    assert any(method.capitalize() in warning for warning in result.warnings)


def test_phosprot_does_not_apply_inherited_normalization_after_collapse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _frame(n_features=100, missing=0.0).rename(
        columns={"ProteinNames": "Phosphoprotein"}
    )
    metadata = pd.DataFrame(
        {
            "sample": SAMPLES,
            "condition": ["control"] * 3 + ["treated"] * 3,
        }
    )
    filter_config = AnnotationFilterConfig(
        normalization="median",
        minPresent=0,
        mode="per_group",
    )
    shared_annotation = SimpleNamespace(
        metadata=metadata,
        filter_config=filter_config,
    )
    monkeypatch.setattr(
        phosprot_tools,
        "_shared_phospho_annotation",
        lambda: shared_annotation,
    )
    monkeypatch.setattr(phosprot_tools, "store_prepared_annotation", lambda stored: vars(stored))
    monkeypatch.setattr(phosprot_tools, "save_table_dataset", lambda **kwargs: None)
    monkeypatch.setattr(phosprot_tools, "clear_annotation", lambda *args, **kwargs: None)

    stored = phosprot_tools._store_phosprot_annotation(
        frame=frame,
        filename="synthetic.csv",
        is_log2_transformed=True,
        warning_prefix="Test phosphoprotein upload.",
    )
    expected = use_existing_log2_data(frame, SAMPLES)

    pd.testing.assert_frame_equal(stored["log2_data"], expected)
    pd.testing.assert_frame_equal(stored["filtered_data"], expected)
    assert stored["filter_config"].normalization == "none"
    assert any(
        "No phosphoprotein-level normalization was applied" in warning
        for warning in stored["warnings"]
    )


def test_phosprot_filter_contract_preserves_filtering_but_forces_no_normalization() -> None:
    inherited = AnnotationFilterConfig(
        method="percentage",
        minPresent=2,
        minPercentage=80.0,
        mode="overall",
        normalization="vsn",
    )

    resolved = phosprot_filter_config(inherited)

    assert resolved.method == inherited.method
    assert resolved.minPresent == inherited.minPresent
    assert resolved.minPercentage == inherited.minPercentage
    assert resolved.mode == inherited.mode
    assert resolved.normalization == "none"
    assert inherited.normalization == "vsn"


def test_phosprot_collapses_normalized_phosphosite_values_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = pd.DataFrame(
        {
            "sample": ["s0", "s1"],
            "condition": ["control", "treated"],
        }
    )
    identifiers = {
        "UPD_seq": ["PEPTIDE1", "PEPTIDE2"],
        "PTM_localization": ["S1", "S2"],
        "Protein_group": ["P1", "P1"],
        "Gene_group": ["G1", "G1"],
        "PTM_Collapse_key": ["P1_S1", "P1_S2"],
    }
    raw_source = pd.DataFrame({**identifiers, "s0": [100.0, 200.0], "s1": [300.0, 400.0]})
    normalized_log2 = pd.DataFrame(
        {
            "s0": [1.0, 2.0],
            "s1": [3.0, 4.0],
            **identifiers,
        }
    )
    shared_annotation = SimpleNamespace(
        source_data=raw_source,
        log2_data=normalized_log2,
        metadata=metadata,
        filter_config=AnnotationFilterConfig(normalization="median", minPresent=0),
        imputation=None,
    )
    monkeypatch.setattr(
        phosprot_tools,
        "_shared_phospho_annotation",
        lambda: shared_annotation,
    )
    monkeypatch.setattr(phosprot_tools, "save_table_dataset", lambda **kwargs: None)
    monkeypatch.setattr(phosprot_tools, "store_prepared_annotation", lambda stored: vars(stored))
    monkeypatch.setattr(phosprot_tools, "clear_annotation", lambda *args, **kwargs: None)

    stored = phosprot_tools.aggregate_from_phospho(
        mode="sum_ignore_na",
        source="non_imputed",
    )

    # Aggregation returns log2 for every mode, so the linear sums 6 and 24 are
    # stored as their logarithms and log2_data must reuse them rather than
    # transform again -- a second log2 here is exactly what "once" rules out.
    assert stored["source_data"].loc[0, "s0"] == pytest.approx(np.log2(6.0))
    assert stored["source_data"].loc[0, "s1"] == pytest.approx(np.log2(24.0))
    assert stored["log2_data"].loc[0, "s0"] == pytest.approx(np.log2(6.0))
    assert stored["log2_data"].loc[0, "s1"] == pytest.approx(np.log2(24.0))
    assert stored["filter_config"].normalization == "none"
    assert any(
        "Phosphosite-level normalization was 'median' before collapse" in warning
        for warning in stored["warnings"]
    )
