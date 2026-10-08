from __future__ import annotations
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
from app.services.annotation_store import save_annotation
from app.services.dataset_store import save_table_dataset
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_qc import render_qc, snapshots
from app.services.plot_images import qc_coverage_plot
from app.services.session_context import get_session_id
from app.services.table_functions import qc_coverage_table


@pytest.fixture
def coverage_data():
    frame = pd.DataFrame({"ProteinNames": ["P1", "P2", "P3"],
        "sample_A_01": [0., 2., np.nan], "sample_A_02": [1., np.nan, np.nan],
        "sample_B_03": [2., 3., np.nan], "sample_B_04": [4., 5., 6.]})
    meta = pd.DataFrame({"sample": list(frame.columns[1:]), "condition": ["A", "A", "B", "B"]})
    save_table_dataset(filename="example.tsv", kind="protein", frame=frame)
    save_annotation(kind="protein", source_data=frame, metadata=meta, log2_data=frame,
                    filtered_data=frame.iloc[:2], is_log2_transformed=True,
                    metadata_source="manual", filter_config=AnnotationFilterConfig(),
                    auto_detected=False, warnings=[], log2_auto_detected=False)
    return frame, meta


@pytest.mark.parametrize("options", [
    {}, {"include_id": True}, {"summary": True}, {"summary": True, "text": True},
    {"legend": False, "header": False, "reference_line": False},
    {"width_cm": 24, "height_cm": 12, "dpi": 90, "text": True},
    {"advanced": {"titleElement": {"text": "A custom title", "size": 17, "bold": True},
                  "xTickLabelRotation": 37, "axisLineTop": False, "axisLineRight": False,
                  "conditionColors": {"A": "#AA1122", "B": "#117744"}}},
])
def test_portable_coverage_matches_ui_png_exactly(coverage_data, options):
    expected = qc_coverage_plot("protein", **options)
    actual, token = render_qc("protein", **options)
    assert bytes(actual) == bytes(expected)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.resources["original.png"] == actual
    assert recipe.settings["random_seed"] == options.get("random_seed", 187)
    assert recipe.provenance["dataSource"] == "data"
    assert not recipe.uses_imputed_input
    expected_table = qc_coverage_table("protein", summary=options.get("summary", False))
    pd.testing.assert_frame_equal(pd.read_parquet(io.BytesIO(recipe.resources["table.parquet"])), expected_table)


@pytest.mark.parametrize("plot,options", [
    ("coverage", {"summary": False, "include_id": True}),
    ("coverage", {"summary": True, "include_id": True}),
    ("boxplot", {"mode": "Mean"}), ("boxplot", {"mode": "Single", "include_id": True}), ("cv", {}),
    ("histogram", {}), ("correlation", {"method": "Ellipse", "include_id": True}),
    ("abundance", {}), ("abundance", {"condition": "B"}),
])
def test_ui_notebook_runs_offline_and_reproduces_plot_and_table(coverage_data, tmp_path, plot, options):
    from app.services import table_functions
    if plot in {"coverage", "boxplot", "cv"}:
        options = {**options, "text": True}
    original, token = render_qc("protein", plot=plot, **options, dpi=90,
                                      advanced={"titleElement": {"text": "Exported coverage"}})
    _, payload = build_notebook_archive(snapshots.get(get_session_id(), token))
    with ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(tmp_path)
        notebook_name = next(name for name in archive.namelist() if name.endswith(".ipynb"))
    notebook = json.loads((tmp_path / notebook_name).read_text())
    cells = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
    cells = set_original_path(cells, tmp_path)
    completed = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.');\n" + cells],
                               cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "reproduced.png").read_bytes() == original
    if plot in {"coverage", "boxplot", "cv"}:
        table_options = {key: value for key, value in options.items() if key in {"summary", "mode"}}
        expected = getattr(table_functions, f"qc_{plot}_table")("protein", **table_options)
        assert (tmp_path / "reproduced_table.csv").read_text() == expected.to_csv(index=False).replace("\r\n", "\n")
    else:
        assert not (tmp_path / "resources/table.parquet").exists()


def test_coverage_download_route_is_frozen_and_session_owned(coverage_data, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.session_context import set_session_id, reset_session_id

    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/plots/qc/protein/coverage.png?dpi=80")
        assert response.status_code == 200
        token = response.headers["X-CoPYlot-Notebook"]
        table_url = f"/api/plots/qc/protein/coverage-table?snapshot={token}"
        original_table = client.get(table_url)
        assert original_table.status_code == 200
        # Later edits must not change the figure's captured numerical inputs.
        coverage_data[0].iloc[0, 1] = np.nan
        assert client.get(table_url).json() == original_table.json()
        assert client.get(table_url + "&summary=true").status_code == 409
        assert client.get(table_url.replace("/protein/", "/phospho/")).status_code == 409
        download = client.get(f"/api/plots/notebooks/{token}.zip")
        assert download.status_code == 200
        assert download.headers["cache-control"] == "no-store"
        assert client.get(f"/api/plots/notebooks/{token}.zip").content == download.content
        with ZipFile(io.BytesIO(download.content)) as archive:
            assert b"GNU GENERAL PUBLIC LICENSE" in archive.read("LICENSE")
            assert archive.read("resources/original.png") == response.content
            captured = pd.read_parquet(io.BytesIO(archive.read("resources/input.parquet")))
            assert captured.iloc[0, 1] == 0.0
        owner = set_session_id("another-session")
        try:
            assert client.get(f"/api/plots/notebooks/{token}.zip").status_code == 404
            assert client.get(table_url).status_code == 404
        finally:
            reset_session_id(owner)
        assert client.get("/api/plots/notebooks/invalid.zip").status_code == 404


def test_concurrent_dataset_edit_does_not_publish_mixed_provenance(coverage_data, monkeypatch):
    from app.services import runtime_cache
    revisions = iter([1, 2])
    monkeypatch.setattr(runtime_cache, "runtime_cache_version", lambda: next(revisions))
    content, token = render_qc("protein", dpi=80)
    assert content.startswith(b"\x89PNG")
    assert token == ""


@pytest.mark.parametrize("plot,options", [
    ("boxplot", {}), ("boxplot", {"mode": "Single", "include_id": True}),
    ("boxplot", {"outliers": True, "text": True, "legend": False}),
    ("boxplot", {"mode": "Single", "text": True, "advanced": {"boxMedianColor": "#008844", "xTickLabelRotation": 25}}),
    ("cv", {}), ("cv", {"outliers": True, "text": True}),
    ("cv", {"legend": False, "header": False, "advanced": {"conditionColors": {"A": "#FF2200"}, "boxBorderColor": "#116622"}}),
])
def test_distribution_exports_match_original_renderers_and_tables(coverage_data, plot, options):
    from app.services import plot_images, table_functions
    original = getattr(plot_images, f"qc_{plot}_plot")("protein", dpi=80, **options)
    content, token = render_qc("protein", plot=plot, dpi=80, **options)
    assert bytes(content) == bytes(original)
    recipe = snapshots.get(get_session_id(), token)
    table_options = {key: value for key, value in options.items() if key == "mode"}
    expected = getattr(table_functions, f"qc_{plot}_table")("protein", **table_options)
    pd.testing.assert_frame_equal(pd.read_parquet(io.BytesIO(recipe.resources["table.parquet"])), expected)
    assert recipe.provenance["inputScale"] == ("linear" if plot == "cv" else "log2")


@pytest.mark.parametrize("plot,params", [("boxplot", "mode=Mean"), ("boxplot", "mode=Single"), ("cv", "")])
def test_distribution_routes_use_matching_snapshot_tables(coverage_data, plot, params):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get(f"/api/plots/qc/protein/{plot}.png?dpi=80&{params}")
        assert response.status_code == 200, response.text
        token = response.headers["X-CoPYlot-Notebook"]
        frozen = client.get(f"/api/plots/qc/protein/{plot}-table?snapshot={token}&{params}")
        live = client.get(f"/api/plots/qc/protein/{plot}-table?{params}")
        assert frozen.status_code == 200
        assert frozen.json() == live.json()
        assert client.get(f"/api/plots/qc/protein/coverage-table?snapshot={token}").status_code == 409
        other = "cv" if plot == "boxplot" else "boxplot"
        assert client.get(f"/api/plots/qc/protein/{other}-table?snapshot={token}").status_code == 409


@pytest.mark.parametrize("plot,options", [
    ("histogram", {}), ("histogram", {"header": False, "legend": False}),
    ("histogram", {"advanced": {"conditionColors": {"A": "#112277"}, "xTickLabelRotation": 20}}),
    ("abundance", {}), ("abundance", {"condition": "A", "legend": False}),
    ("abundance", {"advanced": {"conditionColors": {"B": "#770022"}, "titleElement": {"text": "Abundance"}}}),
    ("correlation", {}), ("correlation", {"method": "Ellipse", "include_id": True, "full_range": True}),
    ("correlation", {"advanced": {"titleElement": {"text": "Correlation"}, "xTickLabelRotation": 35}}),
])
def test_static_qc_exports_match_original_renderers(coverage_data, plot, options):
    from app.services import plot_images
    from app.services.notebook_qc import QC_RENDERERS
    expected = getattr(plot_images, QC_RENDERERS[plot])("protein", dpi=80, **options)
    actual, token = render_qc("protein", plot=plot, dpi=80, **options)
    assert bytes(actual) == bytes(expected)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.provenance["outputs"] == ["plot"]
    assert recipe.provenance["inputScale"] == ("linear" if plot == "abundance" else "log2")
    assert "prepare_table" not in recipe.source.functions


@pytest.mark.parametrize("case", ["empty_condition", "constant_histogram", "complete_correlation"])
def test_static_qc_edge_cases_retain_renderer_parity(coverage_data, case):
    from app.services.annotation_store import get_annotation
    from app.services.runtime_cache import invalidate_runtime_cache
    from app.services import plot_images
    from app.services.notebook_qc import QC_RENDERERS
    frame = get_annotation("protein").log2_data
    if case == "empty_condition":
        frame.loc[:, ["sample_A_01", "sample_A_02"]] = np.nan
    elif case == "constant_histogram":
        frame.loc[:, list(coverage_data[1]["sample"])] = 0.0
    else:
        for index, sample in enumerate(coverage_data[1]["sample"]):
            frame[sample] = np.array([1.0, 3.0, 2.0]) * (index + 1)
    get_annotation('protein').source_data = frame.copy()
    invalidate_runtime_cache("notebook-edge-case")
    plot = "correlation" if case == "complete_correlation" else "histogram"
    expected = getattr(plot_images, QC_RENDERERS[plot])("protein", dpi=80)
    actual, token = render_qc("protein", plot=plot, dpi=80)
    assert bytes(actual) == bytes(expected)
    assert token


@pytest.mark.parametrize("options", [
    {}, {"condition": "B", "legend": False},
    {"advanced": {"conditionColors": {"A": "#BB2200"}, "conditionLabels": {"A": "Renamed"},
                  "titleElement": {"text": "Interactive test", "size": 20}, "xTickLabelRotation": 35}},
])
def test_interactive_abundance_matches_original_and_runs_offline(coverage_data, tmp_path, monkeypatch, options):
    from app.services import plot_images
    from app.services.plot_webgl import force_svg_rendering
    from app.services.notebook_interactive import render_abundance
    from app.services.runtime_cache import invalidate_runtime_cache

    monkeypatch.setattr(plot_images, "_plotly_html", lambda figure: force_svg_rendering(figure).to_json())
    invalidate_runtime_cache("interactive-notebook-parity")
    expected = json.loads(plot_images.qc_abundance_interactive_html("protein", **options))
    html, token = render_abundance("protein", **options)
    recipe = snapshots.get(get_session_id(), token)
    assert json.loads(recipe.resources["figure.json"]) == expected
    assert b"plotly.js" in recipe.resources["original.html"]
    assert "copylot-plot-ready" in html
    _, payload = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(tmp_path)
        notebook_name = next(name for name in archive.namelist() if name.endswith(".ipynb"))
    notebook = json.loads((tmp_path / notebook_name).read_text())
    cells = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
    cells = set_original_path(cells, tmp_path)
    completed = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, '.');\n" + cells],
                               cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "reproduced.html").read_text(encoding="utf-8") == html


def test_dense_interactive_abundance_preserves_svg_fallback(coverage_data, monkeypatch):
    from app.services import plot_images
    from app.services.plot_webgl import force_svg_rendering
    from app.services.notebook_interactive import render_abundance
    from app.services.annotation_store import get_annotation
    annotation = get_annotation('protein')
    dense = pd.concat([annotation.log2_data] * 300, ignore_index=True)
    dense['ProteinNames'] = [f'protein_{index}' for index in range(len(dense))]
    annotation.source_data = dense.copy()
    annotation.log2_data = dense.copy()
    monkeypatch.setattr(plot_images, "_plotly_html", lambda fig: force_svg_rendering(fig).to_json())
    expected = json.loads(plot_images.qc_abundance_interactive_html("protein"))
    _, token = render_abundance("protein")
    actual = json.loads(snapshots.get(get_session_id(), token).resources["figure.json"])
    assert actual == expected
    assert all(trace["type"] == "scatter" for trace in actual["data"])


def test_interactive_route_snapshot_is_session_owned(coverage_data, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    from app.services.session_context import set_session_id, reset_session_id
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/api/plots/qc/protein/abundance-interactive.html?condition=B")
        assert response.status_code == 200
        token = response.headers["X-CoPYlot-Notebook"]
        download = client.get(f"/api/plots/notebooks/{token}.zip")
        assert download.status_code == 200
        with ZipFile(io.BytesIO(download.content)) as archive:
            assert archive.read("resources/original.html") == response.content
            assert json.loads(archive.read("resources/settings.json"))["condition"] == "B"
        owner = set_session_id("another-session")
        try:
            assert client.get(f"/api/plots/notebooks/{token}.zip").status_code == 404
        finally:
            reset_session_id(owner)
