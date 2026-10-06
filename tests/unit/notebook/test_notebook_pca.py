from notebook_replay_support import set_original_path

import io
import json
import subprocess
import sys
from zipfile import ZipFile

import numpy as np
import pandas as pd
import pytest

from app.schemas.annotation import AnnotationFilterConfig
from app.schemas.data_tools import ImputationRunRequest
from app.services.annotation_store import save_annotation, get_annotation
from app.services.dataset_store import save_table_dataset
from app.services.data_tools import run_imputation
from app.services.functions import select_matrix
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_pca import render_pca, _pca_module
from app.services.notebook_qc import snapshots
from app.services.plot_images import qc_pca_plot, _pca_projection
from app.services.session_context import get_session_id


@pytest.fixture
def pca_data():
    samples = [f"{group}_{i}" for group in "AB" for i in range(1, 5)]
    frame = pd.DataFrame(np.random.default_rng(17).normal(12, 2, (14, 8)), columns=samples)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(14)])
    frame.loc[0, samples[0]] = np.nan
    frame.loc[1, samples] = 10.0
    metadata = pd.DataFrame({"sample": samples, "condition": ["A"] * 4 + ["B"] * 4})
    save_table_dataset(filename="pca-input.csv", kind="protein", frame=frame)
    save_annotation(kind="protein", source_data=frame, metadata=metadata, log2_data=frame,
        filtered_data=frame.iloc[:-2].copy(), is_log2_transformed=True, metadata_source="manual",
        filter_config=AnnotationFilterConfig(minPresent=2), auto_detected=False, warnings=[])
    return frame, metadata


@pytest.mark.parametrize("options", [
    {}, {"data_source": "filtered", "scaling": "unit_variance"},
    {"plot_dim": "3D", "legend": False, "header": False},
    {"add_ellipses": True, "advanced": {"conditionColors": {"B": "#771133"}, "titleElement": {"text": "PCA"}}},
    {"cluster_method": "KMeans", "color_by": "Cluster", "cluster_count": 2},
    {"cluster_method": "Agglomerative", "color_by": "Cluster"},
    {"cluster_method": "DBSCAN", "color_by": "Cluster", "dbscan_eps_factor": 0.05},
])
def test_pca_export_matches_original_calculations_and_figure(pca_data, options):
    original = qc_pca_plot("protein", dpi=80, **options)
    actual, token = render_pca("protein", dpi=80, **options)
    assert bytes(actual) == bytes(original)
    recipe = snapshots.get(get_session_id(), token)
    projection_options = {key: value for key, value in options.items() if key in {"plot_dim", "scaling", "data_source"}}
    expected, explained, _ = _pca_projection("protein", **projection_options)
    pd.testing.assert_frame_equal(expected, pd.read_parquet(io.BytesIO(recipe.resources["scores.parquet"])))
    np.testing.assert_array_equal(explained, json.loads(recipe.resources["projection.json"])["explained"])
    assert "umap" not in recipe.source.imports
    assert not recipe.uses_imputed_input


@pytest.mark.parametrize("source,method", [("data", "quantile"), ("filtered", "quantile"),
                                          ("imputed", "quantile"), ("imputed", "numerical")])
def test_pca_notebook_replays_exact_matrix_without_new_imputation(pca_data, tmp_path, source, method):
    run_imputation(ImputationRunRequest(kind="protein", method=method, seed=87, sampleWise=False,
                                       qValue=0.02, adjustStd=0.4, downShift=1.5, width=0.25))
    original, token = render_pca("protein", data_source=source, plot_dim="3D", dpi=80)
    recipe = snapshots.get(get_session_id(), token)
    pd.testing.assert_frame_equal(pd.read_parquet(io.BytesIO(recipe.resources["input.parquet"])), select_matrix("protein", source)[1])
    assert recipe.uses_imputed_input == (source == "imputed")
    assert recipe.provenance["imputation"] == (get_annotation("protein").imputation.model_dump() if source == "imputed" else None)
    if source == "imputed":
        assert "seed=87" in recipe.imputation_recipe
        assert "sample_wise=False" in recipe.imputation_recipe
        assert f"method='{method}'" in recipe.imputation_recipe
    _, payload = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith(".ipynb"))
    notebook = json.loads((tmp_path / name).read_text())
    cells = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
    cells = set_original_path(cells, tmp_path)
    assert "\nimpute_values_with_diagnostics(" not in cells
    result = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.');\n" + cells],
                            cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "reproduced.png").read_bytes() == original


@pytest.mark.parametrize("options", [
    {}, {"plot_dim": "3D", "data_source": "filtered", "scaling": "unit_variance"},
    {"add_ellipses": True, "advanced": {"conditionColors": {"B": "#771133"}}},
    {"cluster_method": "KMeans", "cluster_count": 2, "color_by": "Cluster"},
    {"plot_dim": "3D", "data_source": "imputed"},
])
def test_interactive_pca_parity_and_standalone_replay(pca_data, tmp_path, monkeypatch, options):
    from app.services import plot_images
    from app.services.plot_webgl import force_svg_rendering
    from app.services.runtime_cache import invalidate_runtime_cache
    if options.get("data_source") == "imputed":
        run_imputation(ImputationRunRequest(kind="protein", seed=87))
    monkeypatch.setattr(plot_images, "_plotly_html", lambda fig: force_svg_rendering(fig).to_json())
    invalidate_runtime_cache()
    expected = json.loads(plot_images.qc_pca_interactive_html("protein", **options))
    html, token = render_pca("protein", interactive=True, **options)
    recipe = snapshots.get(get_session_id(), token)
    assert json.loads(recipe.resources["figure.json"]) == expected
    assert "copylot-plot-ready" in html
    assert recipe.uses_imputed_input == (options.get("data_source") == "imputed")
    assert "matplotlib" not in recipe.source.imports
    _, payload = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith(".ipynb"))
    notebook = json.loads((tmp_path / name).read_text())
    cells = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
    cells = set_original_path(cells, tmp_path)
    result = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.');\n" + cells],
                            cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "reproduced.html").read_text(encoding="utf-8") == html


@pytest.mark.parametrize("method", ["UMAP", "t-SNE"])
@pytest.mark.parametrize("interactive", [False, True])
@pytest.mark.parametrize("dimensions,source", [("2D", "filtered"), ("3D", "imputed")])
def test_embedding_parity_and_frozen_notebook_replay(pca_data, tmp_path, monkeypatch, method, interactive, dimensions, source):
    from app.services import plot_images
    from app.services.plot_webgl import force_svg_rendering
    from app.services.runtime_cache import invalidate_runtime_cache
    run_imputation(ImputationRunRequest(kind="protein", seed=87))
    options = dict(method=method, plot_dim=dimensions, data_source=source, random_state=23,
        umap_n_neighbors=3, umap_min_dist=0.2, tsne_perplexity=3, tsne_learning_rate=100,
        cluster_method="KMeans", cluster_count=2, color_by="Cluster", add_ellipses=True,
        advanced={"titleElement": {"text": "Embedding replay"}})
    if interactive:
        monkeypatch.setattr(plot_images, "_plotly_html", lambda fig: force_svg_rendering(fig).to_json())
    else:
        options["dpi"] = 80
    invalidate_runtime_cache()
    renderer = plot_images.qc_pca_interactive_html if interactive else plot_images.qc_pca_plot
    expected = renderer("protein", **options)
    actual, token = render_pca("protein", interactive=interactive, **options)
    recipe = snapshots.get(get_session_id(), token)
    if interactive:
        assert json.loads(recipe.resources["figure.json"]) == json.loads(expected)
    else:
        assert actual == expected
    projection = json.loads(recipe.resources["projection.json"])
    assert projection["explained"] is None
    assert projection["axisPrefix"] == method
    assert recipe.provenance["resolvedScaling"] == "unit_variance"
    assert recipe.provenance["method"] == method
    assert recipe.uses_imputed_input == (source == "imputed")
    assert ("umap" in recipe.source.imports) == (method == "UMAP")
    _, payload = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(tmp_path)
        name = next(name for name in archive.namelist() if name.endswith(".ipynb"))
    if method == "UMAP":
        assert "umap-learn==" in (tmp_path / "requirements.txt").read_text()
    notebook = json.loads((tmp_path / name).read_text())
    cells = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
    cells = set_original_path(cells, tmp_path)
    # A replay must not execute either the stochastic embedding or clustering again.
    guard = "import functions\ndef forbidden(*args, **kwargs): raise AssertionError('Unexpected recalculation')\nfunctions.project = forbidden\nfunctions._compute_cluster_labels = forbidden\n"
    result = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.');\n" + guard + cells],
                            cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    if interactive:
        assert (tmp_path / "reproduced.html").read_text(encoding="utf-8") == actual
    else:
        assert (tmp_path / "reproduced.png").read_bytes() == actual


def test_exported_projection_is_pca_only_and_missing_imputation_provenance_fails_closed(pca_data):
    frame, metadata = pca_data
    with pytest.raises(ValueError, match="PCA only"):
        _pca_module().project(frame, metadata, method="UMAP")
    run_imputation(ImputationRunRequest(kind="protein"))
    get_annotation("protein").imputation.seed = None
    with pytest.raises(ValueError, match="parameters are unavailable"):
        render_pca("protein", data_source="imputed")


def test_pca_route_keeps_plot_available_when_provenance_is_missing(pca_data):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    app = FastAPI()
    app.include_router(router)
    run_imputation(ImputationRunRequest(kind="protein"))
    with TestClient(app) as client:
        response = client.get("/api/plots/qc/protein/pca.png?dataSource=imputed&dpi=80")
        assert response.status_code == 200
        token = response.headers["X-CoPYlot-Notebook"]
        download = client.get(f"/api/plots/notebooks/{token}.zip")
        assert download.status_code == 200
        get_annotation("protein").imputation.seed = None
        fallback = client.get("/api/plots/qc/protein/pca.png?dataSource=imputed&dpi=80")
        assert fallback.status_code == 200
        assert fallback.content == response.content
        assert "X-CoPYlot-Notebook" not in fallback.headers
        assert "X-CoPYlot-Notice" in fallback.headers


def test_interactive_pca_route_exports_and_preserves_missing_provenance_fallback(pca_data):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    app = FastAPI()
    app.include_router(router)
    run_imputation(ImputationRunRequest(kind="protein"))
    with TestClient(app) as client:
        url = "/api/plots/qc/protein/pca-interactive.html?dataSource=imputed&plotDim=3D"
        response = client.get(url)
        assert response.status_code == 200
        token = response.headers["X-CoPYlot-Notebook"]
        assert client.get(f"/api/plots/notebooks/{token}.zip").status_code == 200
        get_annotation("protein").imputation.seed = None
        fallback = client.get(url)
        assert fallback.status_code == 200
        assert "scatter3d" in fallback.text
        assert "X-CoPYlot-Notebook" not in fallback.headers
