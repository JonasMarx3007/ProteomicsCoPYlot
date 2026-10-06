from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.services import plot_images
from proteomicscopylot import notebook_functions


def _missingness_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "s1": [0.0, 4.0, 7.0, np.nan],
            "s2": [1.0, 5.0, np.nan, 8.0],
            "s3": [2.0, 6.0, 9.0, 10.0],
        },
        index=["complete_zero", "complete", "partial_a", "partial_b"],
    )


def test_backend_pca_uses_only_complete_features_without_hidden_imputation() -> None:
    matrix = plot_images._pca_feature_matrix(_missingness_fixture(), n_components=2)

    assert list(matrix.index) == ["complete_zero", "complete"]
    assert matrix.loc["complete_zero", "s1"] == 0.0
    assert not matrix.isna().any().any()


def test_backend_pca_rejects_high_missingness_instead_of_mean_imputing() -> None:
    matrix = _missingness_fixture().drop(index="complete")

    with pytest.raises(ValueError, match="missingness is too high.*Run Imputation"):
        plot_images._pca_feature_matrix(matrix, n_components=2)


def test_pca_feature_summary_reports_complete_variable_features(monkeypatch) -> None:
    frame = _missingness_fixture()
    monkeypatch.setattr(
        plot_images,
        "select_matrix",
        lambda kind, data_source: (data_source, frame.copy(), pd.DataFrame()),
    )
    monkeypatch.setattr(plot_images, "_get_sample_columns", lambda kind, source: ["s1", "s2", "s3"])

    summary = plot_images.qc_pca_feature_summary("protein")

    assert summary == {
        "dbscan": None,
        # PCA has no small-sample caveat; UMAP and t-SNE can (2026-10-02).
        "smallSampleNotice": None,
        "ellipseSkippedGroups": [],
        "featuresTotal": 4,
        "featuresComplete": 2,
        "featuresUsed": 2,
        "featuresRequired": 2,
    }


def test_python_notebook_pca_explains_that_imputation_is_required() -> None:
    frame = _missingness_fixture().drop(index="complete")
    meta = pd.DataFrame(
        {"sample": ["s1", "s2", "s3"], "condition": ["A", "A", "B"]}
    )

    with pytest.raises(ValueError, match="missingness is too high.*Impute the data"):
        notebook_functions.pca_plot(frame, meta)


def _batch_versus_biology() -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(2)
    groups = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    batch = np.array([0, 1, 0, 1, 0, 1, 0, 1])
    features = 3000
    values = rng.normal(0, 0.3, (8, features))
    values[:, :30] += batch[:, None] * rng.normal(0, 12.0, (1, 30))
    values[:, 30:1530] += groups[:, None] * 0.6
    samples = [f"s{i}" for i in range(8)]
    frame = pd.DataFrame(values.T, columns=samples)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(features)])
    metadata = pd.DataFrame({"sample": samples, "condition": ["A"] * 4 + ["B"] * 4})
    return frame, metadata, groups, batch


def _pc1(monkeypatch: pytest.MonkeyPatch, scaling: str, method: str = "PCA") -> np.ndarray:
    from app.services.runtime_cache import invalidate_runtime_cache

    frame, metadata, _, _ = _batch_versus_biology()
    samples = [column for column in frame.columns if column != "ProteinNames"]
    invalidate_runtime_cache(f"pca-scaling-{method}-{scaling}")
    monkeypatch.setattr(
        plot_images, "select_matrix", lambda kind, data_source="data": ("filtered", frame, metadata)
    )
    monkeypatch.setattr(plot_images, "_get_sample_columns", lambda kind, f: samples)
    monkeypatch.setattr(plot_images, "_metadata_for_kind", lambda kind, f, cols: metadata)
    scores, _, _ = plot_images._pca_projection("protein", method=method, scaling=scaling)
    return scores["PC1"].to_numpy()


def test_auto_reproduces_the_established_default_for_each_method() -> None:
    from app.services.functions import resolve_feature_scaling

    assert resolve_feature_scaling("auto", method="PCA") == "centered"
    assert resolve_feature_scaling("auto", method="UMAP") == "unit_variance"
    assert resolve_feature_scaling("auto", method="t-SNE") == "unit_variance"


def test_pca_default_is_unchanged_by_the_new_control(monkeypatch) -> None:
    assert np.allclose(_pc1(monkeypatch, "auto"), _pc1(monkeypatch, "centered"))


def test_scaling_decides_whether_pca_shows_the_batch_or_the_biology(monkeypatch) -> None:
    _, _, groups, batch = _batch_versus_biology()
    centred = _pc1(monkeypatch, "centered")
    scaled = _pc1(monkeypatch, "unit_variance")

    assert abs(np.corrcoef(centred, batch)[0, 1]) > 0.95
    assert abs(np.corrcoef(centred, groups)[0, 1]) < 0.2
    assert abs(np.corrcoef(scaled, groups)[0, 1]) > 0.95
    assert abs(np.corrcoef(scaled, batch)[0, 1]) < 0.2


@pytest.mark.parametrize("bad", ["nonsense", "zscore", "none"])
def test_unknown_scaling_is_rejected(bad: str) -> None:
    from app.services.functions import resolve_feature_scaling

    with pytest.raises(ValueError, match="Unsupported scaling"):
        resolve_feature_scaling(bad)


def test_the_package_exposes_the_same_resolver() -> None:
    from app.services.functions import resolve_feature_scaling as backend

    for method in ("PCA", "UMAP", "t-SNE"):
        assert notebook_functions.resolve_feature_scaling("auto", method) == backend("auto", method)
    for scaling in ("centered", "centred", "unit_variance", "scaled"):
        assert notebook_functions.resolve_feature_scaling(scaling) == backend(scaling)
