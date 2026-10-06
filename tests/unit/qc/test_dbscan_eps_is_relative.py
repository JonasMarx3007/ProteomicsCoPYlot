"""DBSCAN's radius is a fraction of the median inter-sample distance.

An absolute radius means something different on PC scores (tens of log2
units), UMAP (a few units) and t-SNE (tens); the old absolute default of 0.5
labelled every sample "Noise" on any real projection. The factor is what the
page, the routes and the report carry; the effective radius is reported back.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

import numpy as np
import pytest

from app.api import routes_plots
from app.services import plot_images

ROOT = Path(__file__).resolve().parents[3]

# Two groups of three replicates, ~2 units of scatter, 20 units apart -- the
# scale of PC scores on a proteome.
EMBEDDING = np.array(
    [[0.0, 0.0], [1.5, 1.0], [-1.0, 1.8], [20.0, 0.0], [21.5, 1.0], [19.0, 1.8]]
)


def test_median_sample_distance_is_the_median_of_all_pairs():
    points = np.array([[0.0, 0.0], [3.0, 4.0], [6.0, 8.0]])  # distances 5, 10, 5
    assert plot_images.median_sample_distance(points) == 5.0
    assert plot_images.median_sample_distance(points[:1]) == 0.0


def test_effective_eps_scales_with_the_projection():
    eps, median = plot_images.dbscan_effective_eps(EMBEDDING, 0.5)
    assert median == pytest.approx(20.0, abs=2.0)
    assert eps == pytest.approx(0.5 * median)
    # Coincident samples: no usable median, factor is used as an absolute radius.
    eps, median = plot_images.dbscan_effective_eps(np.zeros((4, 2)), 0.5)
    assert (eps, median) == (0.5, 0.0)


def test_default_factor_finds_the_two_groups_where_an_absolute_radius_found_noise():
    pytest.importorskip("sklearn")
    from sklearn.cluster import DBSCAN

    absolute = DBSCAN(eps=0.5, min_samples=2).fit_predict(EMBEDDING)
    assert set(absolute.tolist()) == {-1}, "the old absolute default: every sample is Noise"

    labels = plot_images._compute_cluster_labels(
        EMBEDDING, cluster_method="DBSCAN", dbscan_eps_factor=0.5, dbscan_min_samples=2
    )
    assert labels is not None
    assert -1 not in labels
    assert len(set(labels.tolist())) == 2
    assert len(set(labels[:3].tolist())) == 1 and len(set(labels[3:].tolist())) == 1


def test_feature_summary_reports_the_radius_used(monkeypatch):
    import pandas as pd

    scores = pd.DataFrame(EMBEDDING, columns=["PC1", "PC2"])
    scores["condition"] = ["A", "A", "A", "B", "B", "B"]
    frame = pd.DataFrame({"ProteinNames": ["p1", "p2"], "s1": [1.0, 2.0], "s2": [2.0, 3.0]})
    monkeypatch.setattr(plot_images, "select_matrix", lambda kind, source: (None, frame, None))
    monkeypatch.setattr(plot_images, "_get_sample_columns", lambda kind, df: ["s1", "s2"])
    monkeypatch.setattr(plot_images, "_pca_projection", lambda *a, **k: (scores.copy(), None, "PC"))

    summary = plot_images.qc_pca_feature_summary("protein", cluster_method="DBSCAN", dbscan_eps_factor=0.5)
    dbscan = summary["dbscan"]
    assert dbscan["epsFactor"] == 0.5
    assert dbscan["medianSampleDistance"] == pytest.approx(20.0, abs=2.0)
    assert dbscan["epsEffective"] == pytest.approx(0.5 * dbscan["medianSampleDistance"])

    assert plot_images.qc_pca_feature_summary("protein", cluster_method="KMeans")["dbscan"] is None




def _backend_functions():
    """Every function the backend defines, by module, found by importing it."""
    import app.api as api_package
    import app.services as services_package

    for package in (api_package, services_package):
        for info in pkgutil.iter_modules(package.__path__):
            module = importlib.import_module(f"{package.__name__}.{info.name}")
            for name, value in vars(module).items():
                if inspect.isfunction(value) and value.__module__ == module.__name__:
                    yield f"{module.__name__}.{name}", value


def test_no_absolute_eps_name_survives_anywhere():
    """Clean break: the wire, the routes, the services and the report carry the factor.

    Read from the running backend: no function takes an absolute radius, and
    the published API (frontend/src/lib/generated/openapi.json, checked for
    staleness elsewhere) names none. The frontend half is an ESLint rule
    (frontend/eslint.config.js) and frontend/tests/unit/qc-dbscan-factor.test.tsx.
    """
    offenders = [
        f"{name}({parameter})"
        for name, function in _backend_functions()
        for parameter in inspect.signature(function).parameters
        if parameter in {"dbscan_eps", "dbscanEps"}
        or (parameter == "eps" and "dbscan" in name.lower())
    ]
    assert not offenders, offenders
    published = (ROOT / "frontend" / "src" / "lib" / "generated" / "openapi.json").read_text(encoding="utf-8")
    assert '"dbscanEps"' not in published and '"dbscan_eps"' not in published


def test_routes_accept_the_factor():
    routes_with_factor = {
        name
        for name, function in vars(routes_plots).items()
        if inspect.isfunction(function) and "dbscanEpsFactor" in inspect.signature(function).parameters
    }
    assert len(routes_with_factor) == 3, routes_with_factor
