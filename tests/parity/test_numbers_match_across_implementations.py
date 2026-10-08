"""The app, the pip package and the R functions compute the same numbers.

`test_cross_implementation.py` covers the statistics (volcano, ANOVA, Tukey,
KSEA, normalization, filtering). This file covers what it did not:

- PCA scores and explained variance, centred and with unit-variance scaling;
- the sample correlation matrix;
- the two completeness tables;
- the values behind the single-protein boxplot.

VSN (app vs R) is compared in tests/parity/test_vsn_bridge.py.

All three run on the bundled HEK293 example, loaded the way the app loads it.
Where the app does not expose a function, the code it actually runs is used:
the notebook module behind the QC correlation page, and the PCA projection.
A component's sign is arbitrary, so PCA scores are compared up to sign.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]

from proteomicscopylot import notebook_functions as pip_package  # noqa: E402

KINDS = ("protein", "phospho")


from _r_runtime import RSCRIPT
pytestmark = pytest.mark.usefixtures("example_project")
requires_r = pytest.mark.requires_r()


def _projection_input(kind):
    from app.services.data_tools import _get_sample_columns, metadata_for_kind
    from app.services.functions import select_matrix

    _, frame, _ = select_matrix(kind, "data")
    return frame, metadata_for_kind(kind, frame, _get_sample_columns(kind, frame)).copy()


def _qc_input(kind):
    from app.services.data_tools import _get_sample_columns, log2_qc_frame, metadata_for_kind

    frame = log2_qc_frame(kind).copy()
    return frame, metadata_for_kind(kind, frame, _get_sample_columns(kind, frame)).copy()


def _completeness_input(kind):
    from app.services import completeness_tools

    return completeness_tools._frame_and_meta(kind)


def _single_input(kind):
    from app.services.functions import select_matrix

    _, frame, metadata = select_matrix(kind, "data")
    label = "ProteinNames" if kind == "protein" else "PTM_Collapse_key"
    samples = metadata["sample"].astype(str).tolist()
    values = frame[samples].apply(pd.to_numeric, errors="coerce")
    partly_missing = frame.loc[values.index[values.isna().any(axis=1) & values.notna().sum(axis=1).ge(4)], label]
    complete = frame.loc[values.index[values.notna().all(axis=1)], label]
    features = [str(complete.iloc[0]), str(partly_missing.iloc[0])]
    groups = frame.loc[frame[label].astype(str).str.contains(";", regex=False), label]
    if not groups.empty:
        features = list(dict.fromkeys([*features, str(groups.iloc[0])]))
    return frame, metadata, label, features


def _align_signs(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    signs = np.sign(np.sum(left * right, axis=0))
    signs[signs == 0] = 1.0
    return right * signs


# --- the app side -------------------------------------------------------------


def _app_pca(kind, scaling):
    from app.services import plot_images

    scores, explained, _ = plot_images._pca_projection(kind, "data", scaling=scaling)
    return scores, np.asarray(explained[:2], dtype=float)


def _app_correlation(kind) -> pd.DataFrame:
    from app.services import notebook_qc

    data, metadata = _qc_input(kind)
    figure = notebook_qc._qc_module("correlation").plot_figure(data, metadata, {}, include_id=False)
    try:
        axis = figure.axes[0]
        labels = [label.get_text() for label in axis.get_xticklabels()]
        # The matrix is drawn as a mesh, one rectangle per cell (vector in SVG/PDF).
        from matplotlib.collections import QuadMesh

        mesh = next(child for child in axis.collections if isinstance(child, QuadMesh))
        values = np.ma.filled(np.ma.asarray(mesh.get_array(), dtype=float), np.nan).reshape(len(labels), len(labels))
    finally:
        import matplotlib.pyplot as plt

        plt.close(figure)
    return pd.DataFrame(values, index=labels, columns=labels)


def _app_completeness(kind):
    from app.services import completeness_tools

    return (completeness_tools.completeness_sample_summary_table(kind, include_id=True),
            completeness_tools.completeness_feature_summary_table(kind, include_id=True))


def _app_single(kind, feature):
    from app.services import notebook_single

    frame, metadata, _, _ = _single_input(kind)
    arrays, conditions, _, _ = notebook_single.box_module().prepare_table(frame, metadata, kind, feature, [], "workflow")
    return {str(condition): sorted(float(v) for v in values) for condition, values in zip(conditions, arrays)}


# --- R ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def r_results(tmp_path_factory, require_r, example_project):
    require_r()
    out: dict[str, dict[str, pd.DataFrame]] = {}
    for kind in KINDS:
        directory = tmp_path_factory.mktemp(f"r_{kind}")
        projection, projection_meta = _projection_input(kind)
        qc, qc_meta = _qc_input(kind)
        completeness, completeness_meta = _completeness_input(kind)
        single, single_meta, label, features = _single_input(kind)
        inputs = {
            "projection": (projection, projection_meta),
            "qc": (qc, qc_meta),
            "completeness": (completeness, completeness_meta),
            "single": (single[[label, *single_meta["sample"].astype(str)]], single_meta),
        }
        for name, (frame, meta) in inputs.items():
            frame.to_csv(directory / f"{name}.csv", index=False)
            meta[["sample", "condition"]].to_csv(directory / f"{name}_meta.csv", index=False)
        feature_list = ", ".join(f'"{feature}"' for feature in features)
        d = directory.as_posix()
        script = f"""
        suppressPackageStartupMessages(source("{(ROOT / 'proteomicscopylot' / 'notebook_functions.R').as_posix()}"))
        read <- function(name) read.csv(file.path("{d}", paste0(name, ".csv")), check.names = FALSE, stringsAsFactors = FALSE)
        save <- function(x, name) write.csv(x, file.path("{d}", paste0("out_", name, ".csv")), row.names = FALSE)
        for (scaling in c("centered", "unit_variance")) {{
          scores <- pca_scores(read("projection"), read("projection_meta"), scaling = scaling)
          save(scores, paste0("pca_", scaling))
          save(data.frame(explained = attr(scores, "explained_variance")), paste0("explained_", scaling))
        }}
        correlation <- sample_correlation_matrix(read("qc"), read("qc_meta"), id = FALSE)
        save(cbind(label = rownames(correlation), as.data.frame(correlation, check.names = FALSE)), "correlation")
        save(missing_sample_table(read("completeness"), read("completeness_meta"), id = TRUE), "missing_sample")
        save(missing_protein_table(read("completeness"), read("completeness_meta"), id = TRUE), "missing_feature")
        single <- read("single")
        for (feature in c({feature_list})) {{
          save(single_protein_values(single, read("single_meta"), feature), paste0("single_", make.names(feature)))
        }}
        """
        completed = subprocess.run([RSCRIPT, "-e", script], capture_output=True, text=True, timeout=900)
        assert completed.returncode == 0, completed.stderr[-3000:]
        out[kind] = {path.stem.removeprefix("out_"): pd.read_csv(path) for path in directory.glob("out_*.csv")}
        out[kind]["_features"] = features
    return out


# --- PCA ----------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("scaling", ["centered", "unit_variance"])
def test_pca_scores_match_between_the_app_and_the_pip_package(kind, scaling):
    app_scores, app_explained = _app_pca(kind, scaling)
    frame, meta = _projection_input(kind)
    pip_scores = pip_package.pca_scores(frame, meta, scaling=scaling)
    assert pip_scores["sample"].astype(str).tolist() == app_scores["sample"].astype(str).tolist()
    left = app_scores[["PC1", "PC2"]].to_numpy(float)
    right = _align_signs(left, pip_scores[["PC1", "PC2"]].to_numpy(float))
    np.testing.assert_allclose(right, left, rtol=1e-8, atol=1e-8)
    np.testing.assert_allclose(pip_scores.attrs["explained_variance"], app_explained, rtol=1e-8)


@requires_r
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("scaling", ["centered", "unit_variance"])
def test_pca_scores_match_between_the_app_and_r(r_results, kind, scaling):
    app_scores, app_explained = _app_pca(kind, scaling)
    r_scores = r_results[kind][f"pca_{scaling}"]
    assert r_scores["sample"].astype(str).tolist() == app_scores["sample"].astype(str).tolist()
    left = app_scores[["PC1", "PC2"]].to_numpy(float)
    right = _align_signs(left, r_scores[["PC1", "PC2"]].to_numpy(float))
    np.testing.assert_allclose(right, left, rtol=1e-7, atol=1e-7)
    np.testing.assert_allclose(r_results[kind][f"explained_{scaling}"]["explained"], app_explained, rtol=1e-7)


def test_pca_plot_leaves_the_callers_metadata_alone():
    frame, meta = _projection_input("protein")
    before = meta.copy(deep=True)
    figure = pip_package.pca_plot(frame, meta)
    import matplotlib.pyplot as plt

    plt.close(figure)
    pd.testing.assert_frame_equal(meta, before)


# --- correlation --------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_the_correlation_matrix_matches_between_the_app_and_the_pip_package(kind):
    app = _app_correlation(kind)
    data, meta = _qc_input(kind)
    pip = pip_package.sample_correlation_matrix(data, meta, id=False)
    assert sorted(pip.index) == sorted(app.index)
    np.testing.assert_allclose(pip.loc[app.index, app.columns].to_numpy(float), app.to_numpy(float),
                               rtol=1e-10, atol=1e-12, equal_nan=True)


@requires_r
@pytest.mark.parametrize("kind", KINDS)
def test_the_correlation_matrix_matches_between_the_app_and_r(r_results, kind):
    app = _app_correlation(kind)
    r_matrix = r_results[kind]["correlation"].set_index("label")
    assert sorted(r_matrix.index) == sorted(app.index)
    np.testing.assert_allclose(r_matrix.loc[app.index, app.columns].to_numpy(float), app.to_numpy(float),
                               rtol=1e-10, atol=1e-12, equal_nan=True)


# --- completeness -------------------------------------------------------------

# Rows with no value in any sample ("identified, not quantified") are left out by
# all three; the phosphosite example has 21 of them, which is why it is a case.
COMPLETENESS_KINDS = ["protein", "phospho"]


def _assert_completeness_equal(app_samples, app_features, samples, features):
    assert samples["Sample"].astype(str).tolist() == app_samples["Sample"].astype(str).tolist()
    assert samples["Counts"].astype(int).tolist() == app_samples["Counts"].astype(int).tolist()
    np.testing.assert_allclose(samples["%_missing_values"].round(2), app_samples["%_missing_values"], atol=1e-9)
    assert features["n_MissingProteinValues"].astype(int).tolist() == app_features["n_MissingProteinValues"].astype(int).tolist()
    assert features["Counts"].astype(int).tolist() == app_features["Counts"].astype(int).tolist()
    np.testing.assert_allclose(features["%_missing_values"].round(2), app_features["%_missing_values"], atol=1e-9)


@pytest.mark.parametrize("kind", COMPLETENESS_KINDS)
def test_completeness_tables_match_between_the_app_and_the_pip_package(kind):
    frame, meta = _completeness_input(kind)
    _assert_completeness_equal(*_app_completeness(kind),
                               pip_package.missing_sample_table(frame, meta, id=True),
                               pip_package.missing_protein_table(frame, meta, id=True))


@requires_r
@pytest.mark.parametrize("kind", COMPLETENESS_KINDS)
def test_completeness_tables_match_between_the_app_and_r(r_results, kind):
    _assert_completeness_equal(*_app_completeness(kind),
                               r_results[kind]["missing_sample"], r_results[kind]["missing_feature"])


# --- single protein -----------------------------------------------------------


def _grouped(table: pd.DataFrame) -> dict[str, list[float]]:
    return {str(condition): sorted(float(v) for v in group["value"])
            for condition, group in table.groupby("condition", sort=False)}


@pytest.mark.parametrize("kind", KINDS)
def test_single_protein_values_match_between_the_app_and_the_pip_package(kind):
    frame, meta, label, features = _single_input(kind)
    columns = [label, *meta["sample"].astype(str)]
    for feature in features:
        pip = _grouped(pip_package.single_protein_values(frame[columns], meta, feature))
        app = _app_single(kind, feature)
        assert pip.keys() == app.keys(), feature
        for condition in app:
            np.testing.assert_allclose(pip[condition], app[condition], rtol=1e-12, err_msg=f"{feature} {condition}")


@requires_r
@pytest.mark.parametrize("kind", KINDS)
def test_single_protein_values_match_between_the_app_and_r(r_results, kind):
    import re

    for feature in r_results[kind]["_features"]:
        name = "single_" + re.sub(r"[^A-Za-z0-9._]", ".", feature if feature[:1].isalpha() or feature[:1] == "." else "X" + feature)
        r_values = _grouped(r_results[kind][name])
        app = _app_single(kind, feature)
        assert r_values.keys() == app.keys(), feature
        for condition in app:
            np.testing.assert_allclose(r_values[condition], app[condition], rtol=1e-12, err_msg=f"{feature} {condition}")
