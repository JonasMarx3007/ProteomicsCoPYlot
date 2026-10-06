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
from app.services import completeness_tools
from app.services.notebook_archive import build_notebook_archive
from app.services.notebook_completeness import render_completeness
from app.services.notebook_qc import snapshots
from app.services.session_context import get_session_id
from test_notebook_phosprot import phosphosites  # Shared real collapse/imputation fixture.
from test_notebook_peptide import peptide_input


@pytest.fixture(autouse=True)
def isolated_inputs():
    from app.services.dataset_store import reset_all_datasets
    from app.services.annotation_store import reset_all_annotations
    reset_all_datasets()
    reset_all_annotations()
    yield
    reset_all_datasets()
    reset_all_annotations()


@pytest.fixture(params=["protein", "phospho"])
def completeness_data(request):
    kind = request.param
    key = "ProteinNames" if kind == "protein" else "PTM_Collapse_key"
    frame = pd.DataFrame({key: ["P1", "P2", "P3", "P4"],
                          "run_01": [0., 4., np.nan, 1.], "run_02": [1., np.nan, np.nan, 2.],
                          "run_03": [3., np.nan, np.nan, 3.]})
    meta = pd.DataFrame({"sample": list(frame.columns[1:]), "condition": ["A", "A", "B"]})
    save_table_dataset(kind=kind, filename=r"C:\private\study\input.tsv", frame=frame)
    save_annotation(kind=kind, source_data=frame, metadata=meta, log2_data=frame.assign(run_01=99.),
                    filtered_data=frame.iloc[:1], is_log2_transformed=True,
                    metadata_source="manual", filter_config=AnnotationFilterConfig(),
                    auto_detected=False, warnings=[], log2_auto_detected=False)
    return kind, frame


@pytest.mark.parametrize("plot,options", [
    ("missing-value", {}), ("missing-value", {"bin_count": 1, "text": False}),
    ("missing-value", {"advanced": {"barColor": "#112233", "valueLabelSize": 12,
                                    "titleElement": {"text": "Observed features", "bold": True}}}),
    ("missing-heatmap", {}), ("missing-heatmap", {"include_id": False, "header": False,
        "advanced": {"sampleLabels": {"run_01": "Renamed sample"}, "xTickLabelRotation": 35}}),
])
def test_completeness_replays_exact_plot_and_tables(completeness_data, tmp_path, plot, options):
    kind, frame = completeness_data
    renderer = (completeness_tools.completeness_missing_value_plot if plot == "missing-value"
                else completeness_tools.completeness_missing_value_heatmap)
    expected = renderer(kind, dpi=80, **options)
    actual, token = render_completeness(kind, plot=plot, dpi=80, table_include_id=False,
                                        outlier_threshold=30., **options)
    assert bytes(actual) == bytes(expected)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.provenance["excludedAllMissingCount"] == 1
    assert not recipe.uses_imputed_input
    assert not recipe.provenance["normalizationAppliedToThisPlot"]
    data = pd.read_parquet(io.BytesIO(recipe.resources["input.parquet"]))
    pd.testing.assert_frame_equal(data, frame)
    _, payload = build_notebook_archive(recipe)
    with ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(tmp_path)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["originalFilename"] == "input.tsv"
        notebook_name = next(name for name in archive.namelist() if name.endswith(".ipynb"))
    notebook = json.loads((tmp_path / notebook_name).read_text())
    cells = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
    cells = set_original_path(cells, tmp_path)
    result = subprocess.run([sys.executable, "-I", "-c", "import sys;sys.path.insert(0,'.');\n" + cells],
                            cwd=tmp_path, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "reproduced.png").read_bytes() == actual
    tables = completeness_tools.completeness_tables(kind, include_id=False, outlier_threshold=30.)
    expected_outliers = pd.DataFrame({"Sample": tables.outliers}).to_csv(index=False, lineterminator="\n")
    assert (tmp_path / "reproduced_outliers.csv").read_text() == expected_outliers


@pytest.mark.parametrize("plot", ["missing-value", "missing-heatmap"])
def test_completeness_route_captures_table_options(completeness_data, plot):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_plots import router
    kind, _ = completeness_data
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.get(f"/api/plots/completeness/{kind}/{plot}.png?dpi=80&tableIncludeId=false&outlierThreshold=23")
        assert response.status_code == 200, response.text
        token = response.headers["X-CoPYlot-Notebook"]
        recipe = snapshots.get(get_session_id(), token)
        assert recipe.settings["outlier_threshold"] == 23
        assert recipe.settings["table_include_id"] is False
        assert client.get(f"/api/plots/notebooks/{token}.zip").status_code == 200


def test_changed_source_during_render_does_not_publish_snapshot(completeness_data, monkeypatch):
    from app.services import runtime_cache
    revisions = iter([1, 2])
    monkeypatch.setattr(runtime_cache, "runtime_cache_version", lambda: next(revisions))
    content, token = render_completeness(completeness_data[0], plot="missing-value", dpi=80)
    assert content.startswith(b"\x89PNG")
    assert token == ""


@pytest.mark.parametrize("plot", ["missing-value", "missing-heatmap"])
@pytest.mark.parametrize("source", ["non_imputed", "imputed"])
def test_phosprot_completeness_keeps_collapse_history(phosphosites, plot, source):
    from app.services.phosprot_tools import aggregate_from_phospho
    from app.services.annotation_store import get_annotation
    aggregate_from_phospho("robust_site_median", source)
    renderer = (completeness_tools.completeness_missing_value_plot if plot == "missing-value"
                else completeness_tools.completeness_missing_value_heatmap)
    expected = renderer("phosprot", dpi=80)
    actual, token = render_completeness("phosprot", plot=plot, dpi=80)
    assert bytes(actual) == bytes(expected)
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.uses_imputed_input == (source == "imputed")
    assert recipe.provenance["upstreamCollapse"] == get_annotation("phosprot").phosprot_lineage.model_dump()
    if source == "imputed":
        assert "seed=87" in recipe.imputation_recipe
    build_notebook_archive(recipe)


def test_linear_zeros_and_nonfinite_values_are_captured_as_missing(completeness_data):
    from app.services.annotation_store import get_annotation
    kind, _ = completeness_data
    annotation = get_annotation(kind)
    annotation.is_log2_transformed = False
    annotation.source_data.loc[0, "run_02"] = np.inf
    _, token = render_completeness(kind, plot="missing-value", dpi=80)
    recipe = snapshots.get(get_session_id(), token)
    data = pd.read_parquet(io.BytesIO(recipe.resources["input.parquet"]))
    assert pd.isna(data.loc[0, "run_01"])
    assert pd.isna(data.loc[0, "run_02"])
    assert recipe.provenance["zeroIsMissing"] is True


def test_unannotated_completeness_plot_remains_available(monkeypatch):
    from app.api.routes_plots import _completeness_notebook_plot
    from app.services import annotation_store
    monkeypatch.setattr(annotation_store, "get_annotation", lambda kind: None)
    monkeypatch.setattr("app.api.routes_plots.completeness_missing_value_plot", lambda **kwargs: b"original")
    response = _completeness_notebook_plot("missing-value", kind="protein", table_include_id=True, outlier_threshold=50.)
    assert response.body == b"original"
    assert "X-CoPYlot-Notebook" not in response.headers


@pytest.mark.parametrize("plot", ["missing-value", "missing-heatmap"])
def test_snapshot_tables_match_live_then_remain_frozen_and_owned(completeness_data, plot, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.routes_data_tools import router
    from app.services.annotation_store import get_annotation
    from app.services.session_context import set_session_id, reset_session_id
    kind, _ = completeness_data
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    _, token = render_completeness(kind, plot=plot, table_include_id=False, outlier_threshold=30., dpi=80)
    expected = completeness_tools.completeness_tables(kind, include_id=False, outlier_threshold=30.).model_dump()
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        url = f"/api/data-tools/completeness/{kind}/tables?includeId=false&outlierThreshold=30&snapshot={token}"
        assert client.get(url).json() == expected
        get_annotation(kind).source_data.loc[:, "run_01"] = np.nan
        assert client.get(url).json() == expected
        assert client.get(url.replace("Threshold=30", "Threshold=31")).status_code == 409
        assert client.get(url.replace("includeId=false", "includeId=true")).status_code == 409
        assert client.get(url.replace(f"/{kind}/", "/phosprot/")).status_code == 409
        other = set_session_id("different-reader")
        try:
            assert client.get(url).status_code == 404
        finally:
            reset_session_id(other)


@pytest.mark.parametrize("level", ["peptide", "precursor"])
@pytest.mark.parametrize("quantity", ["Precursor.Quantity", "Alternative.Quantity"])
def test_peptide_completeness_notebook_is_exact_and_independent(peptide_input, tmp_path, level, quantity):
    from app.services.notebook_completeness import render_peptide_missing_values
    options = dict(quantity_column=quantity, dpi=80, bin_count=1,
                   advanced={"barColor": "#008866", "xTickLabelRotation": 25})
    original = getattr(completeness_tools, f"completeness_missing_value_plot_{level}")(**options)
    actual, token = render_peptide_missing_values(level, **options)
    assert actual == original
    recipe = snapshots.get(get_session_id(), token)
    assert recipe.provenance["quantityColumn"] == quantity
    assert recipe.provenance["kind"] == level
    _, payload = build_notebook_archive(recipe)
    output = tmp_path / "notebook"
    output.mkdir()
    with ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(output)
        name = next(name for name in archive.namelist() if name.endswith(".ipynb"))
    notebook = json.loads((output / name).read_text())
    cells = "\n".join("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code")
    cells = set_original_path(cells, output)
    result = subprocess.run([sys.executable, "-I", "-c", "import sys;sys.path.insert(0,'.');\n" + cells],
                            cwd=output, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert (output / "reproduced.png").read_bytes() == actual


def test_peptide_run_paths_are_removed_without_merging_samples(peptide_input):
    from app.services.notebook_completeness import render_peptide_missing_values
    from app.services.dataset_store import save_peptide_path
    from app.services.peptide_metadata_store import save_peptide_metadata
    runs = [r"C:\secret\run.raw", "/private/run.raw", "run.raw (2)"]
    pd.DataFrame({'File.Name': runs * 2, 'Precursor.Id': ['AAA2'] * 3 + ['BBB2'] * 3,
        'Stripped.Sequence': ['AAA'] * 3 + ['BBB'] * 3,
        'Precursor.Quantity': [1., np.nan, 2., 2., 3., 4.]}).to_csv(peptide_input, index=False)
    save_peptide_path(str(peptide_input))
    save_peptide_metadata('metadata.csv', pd.DataFrame({'sample': runs, 'condition': ['A', 'B', 'C']}))
    _, token = render_peptide_missing_values("precursor", dpi=80)
    recipe = snapshots.get(get_session_id(), token)
    captured = pd.read_parquet(io.BytesIO(recipe.resources["input.parquet"]))
    assert captured.columns.tolist() == ["run.raw", "run.raw (2)", "run.raw (2) (2)"]
    assert captured.shape == (2, 3)
    assert all(path not in recipe.resources['processing.json'].decode() for path in runs[:2])
