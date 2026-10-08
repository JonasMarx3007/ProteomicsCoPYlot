"""The app starts, answers its health routes and survives bad input.

The imputation, enrichment and clustering checks that used to live here were
moved to their own files on 2026-10-02."""
from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.annotation import AnnotationFilterConfig, AnnotationImputationInfo
from app.services.annotation_store import get_annotation
from app.services.viewer_bootstrap import load_viewer_state


ROOT = Path(__file__).resolve().parents[3]




def test_all_backend_modules_import() -> None:
    modules = sorted(
        {
            ".".join(path.relative_to(ROOT / "backend").with_suffix("").parts)
            for path in (ROOT / "backend" / "app").rglob("*.py")
            if path.name != "__init__.py"
        }
    )
    assert len(modules) >= 60
    for module_name in modules:
        importlib.import_module(module_name)


def test_health_runtime_and_openapi_routes() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["message"] == "Backend is running"

        runtime = client.get("/api/runtime/r?refresh=1")
        assert runtime.status_code == 200
        payload = runtime.json()
        assert isinstance(payload["available"], bool)
        assert isinstance(payload["candidates"], list)

        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        schema = openapi.json()
        paths = schema["paths"]
        assert "/api/runtime/r" in paths
        assert "/api/external/peptide-collapse/upload" in paths
        # The path-based variant read and wrote server paths and nothing called it.
        assert "/api/external/peptide-collapse/run" not in paths
        assert "/api/stats/ora/run" in paths
        assert "/api/stats/ora/list/run" in paths
        assert all("gsea" not in path.lower() for path in paths)

        volcano_parameters = {
            parameter["name"]: parameter["schema"]
            for parameter in paths["/api/plots/stats/{kind}/volcano.html"]["get"]["parameters"]
        }
        simulation_parameters = {
            parameter["name"]: parameter["schema"]
            for parameter in paths["/api/plots/stats/{kind}/simulation.html"]["get"]["parameters"]
        }
        assert set(volcano_parameters["testType"]["enum"]) == {
            "unpaired",
            "unpaired_welch",
            "paired",
        }
        assert simulation_parameters["testType"]["enum"] == [
            "unpaired",
            "unpaired_welch",
        ]
        assert "source" not in simulation_parameters
        assert "condition1Control" not in simulation_parameters
        assert "condition2Control" not in simulation_parameters


def test_invalid_peptide_upload_is_controlled_and_server_survives() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/external/peptide-collapse/upload",
            files={
                "file": (
                    "invalid.tsv",
                    b"column_a\tcolumn_b\n1\t2\n",
                    "text/tab-separated-values",
                )
            },
        )
        assert response.status_code == 400
        assert "needed columns" in response.json()["detail"]
        assert client.get("/api/health").status_code == 200


def test_default_viewer_configuration_loads_canonical_example_data() -> None:
    result = load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    loaded_datasets = {entry.rsplit(":", 1)[-1] for entry in result.loaded_datasets}
    assert {"protein", "phospho", "phosprot"} <= loaded_datasets
    assert any(entry.endswith(":WT_vs_GRK") for entry in result.loaded_annotations)


def test_report_mentions_annotation_filtering() -> None:
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    protein_annotation = get_annotation("protein")
    assert protein_annotation is not None
    protein_annotation.filter_config = AnnotationFilterConfig(
        method="percentage",
        minPercentage=70,
        mode="overall",
    )
    protein_annotation.imputation = AnnotationImputationInfo(
        mode="numerical",
        # The tool only ever stores applied=True, on success; applied=False with
        # a real mode means the imputation was asked for and refused, and the
        # report deliberately does not describe those settings as if they had
        # been used. This fixture is about the wording of a successful
        # imputation, so it has to say so.
        applied=True,
        downShift=1.8,
        width=0.3,
        seed=1337,
        sampleWise=False,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/summary/report",
            json={
                "title": "Filtering report",
                "author": "Test",
                "reportContext": {
                    "qcSettings": {
                        "protein": {"pca": {"dataSource": "imputed"}},
                        "phospho": {"pca": {"dataSource": "data"}},
                    }
                },
            },
        )
    assert response.status_code == 200
    report_html = response.json()["html"]
    # Two level preambles plus the two PCA blocks, which now carry the same
    # provenance block as a volcano: source, then filtering, then imputation.
    assert report_html.count("<strong>Filtering:</strong>") == 4
    assert (
        "Rows with at least 70% completeness across all annotated samples, "
        "independent of condition groups were retained ("
    ) in report_html
    assert (
        "Rows with at least 3 valid values in at least one condition group were retained ("
    ) in report_html
    # Row counts appear with every filtering line: "(kept of source rows)" where
    # the filter was applied, "uses all N rows ... keeps M rows" where it was not.
    # The example project applies no normalization, so no normalization lines.
    assert report_html.count("<strong>Normalization:</strong>") == 0
    assert report_html.count(" of ") >= 2 and report_html.count("it uses all ") >= 1
    assert "<strong>Data source:</strong> Imputed Data" in report_html
    assert "<strong>Data source:</strong> Data" in report_html
    imputation_text = (
        "For analyses based on imputed data, missing values were sampled from a shifted "
        "normal distribution with a downshift of 1.8 standard deviations and width "
        "0.3 times the observed standard deviation (Tyanova et al. 2016, doi:10.1038/nmeth.3901)."
    )
    assert imputation_text in report_html
    assert report_html.index(imputation_text) < report_html.index(
        "<strong>Data source:</strong> Imputed Data"
    )
