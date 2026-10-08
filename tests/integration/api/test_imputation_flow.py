"""Imputation through the API: stored, reused, offered and invalidated.

Moved out of test_api_smoke.py (2026-10-02)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.annotation_store import get_annotation, save_annotation
from app.services.restore_state import _parse_state_blob, export_state_blob
from app.services.viewer_bootstrap import load_viewer_state


ROOT = Path(__file__).resolve().parents[3]




def test_numerical_imputation_api_persists_and_renders() -> None:
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    with TestClient(app) as client:
        response = client.post(
            "/api/data-tools/imputation/run",
            json={
                "kind": "protein",
                "method": "numerical",
                "downShift": 1.8,
                "width": 0.3,
                "seed": 1337,
                "sampleWise": False,
            },
        )
        assert response.status_code == 200
        assert response.json()["method"] == "numerical"
        assert response.json()["downShift"] == 1.8
        assert response.json()["width"] == 0.3

        annotation = client.get("/api/annotations/current/protein")
        assert annotation.status_code == 200
        assert annotation.json()["imputation"]["mode"] == "numerical"
        assert annotation.json()["imputation"]["applied"] is True
        assert annotation.json()["imputation"]["downShift"] == 1.8
        assert annotation.json()["imputation"]["width"] == 0.3

        stored = get_annotation("protein")
        assert stored is not None
        assert not stored.imputed_data.empty
        assert stored.imputed_data.shape == stored.filtered_data.shape

        exported = _parse_state_blob(export_state_blob())
        protein_annotations = [
            entry
            for package in exported["backend"]["packages"]
            for entry in package.get("annotations", [])
            if entry.get("kind") == "protein"
        ]
        assert any(entry.get("imputedFrame") is not None for entry in protein_annotations)

        plot = client.get(
            "/api/plots/imputation/protein/overall-fit.png",
            params={
                "method": "numerical",
                "downShift": 1.8,
                "width": 0.3,
            },
        )
        assert plot.status_code == 200
        assert plot.content.startswith(b"\x89PNG")
        quantile_plot = client.get(
            "/api/plots/imputation/protein/overall-fit.png",
            params={
                "method": "quantile",
                "qValue": 0.01,
                "adjustStd": 0.3,
            },
        )
        assert quantile_plot.status_code == 200
        assert plot.content != quantile_plot.content

        invalid = client.post(
            "/api/data-tools/imputation/run",
            json={"kind": "protein", "method": "unsupported"},
        )
        assert invalid.status_code == 422


def test_qc_pca_supports_data_and_configured_imputed_sources() -> None:
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    with TestClient(app) as client:
        before_options = client.get("/api/plots/qc/protein/options")
        assert before_options.status_code == 200
        assert before_options.json()["imputedAvailable"] is False

        imputation = client.post(
            "/api/data-tools/imputation/run",
            json={
                "kind": "protein",
                "qValue": 0.01,
                "adjustStd": 0.5,
                "seed": 1337,
                "sampleWise": False,
            },
        )
        assert imputation.status_code == 200

        after_options = client.get("/api/plots/qc/protein/options")
        assert after_options.status_code == 200
        assert after_options.json()["imputedAvailable"] is True

        for data_source in ("data", "imputed"):
            response = client.get(
                "/api/plots/qc/protein/pca.png",
                params={"dataSource": data_source, "dpi": 72},
            )
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
            assert response.content.startswith(b"\x89PNG")

        interactive = client.get(
            "/api/plots/qc/protein/pca-interactive.html",
            params={"dataSource": "imputed"},
        )
        assert interactive.status_code == 200
        assert "plotly" in interactive.text.lower()

        invalid = client.get(
            "/api/plots/qc/protein/pca.png",
            params={"dataSource": "invalid"},
        )
        assert invalid.status_code == 400


def test_ksea_offers_only_successfully_materialized_imputed_data() -> None:
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    with TestClient(app) as client:
        options = client.get("/api/plots/phospho/options")
        assert options.status_code == 200
        option_payload = options.json()
        assert option_payload["imputedAvailable"] is False
        condition1, condition2 = option_payload["conditions"][:2]

        unavailable = client.get(
            "/api/plots/phospho/ksea-table",
            params={
                "condition1": condition1,
                "condition2": condition2,
                "dataSource": "imputed",
            },
        )
        assert unavailable.status_code == 400
        assert "Run imputation successfully first" in unavailable.json()["detail"]

        imputation = client.post(
            "/api/data-tools/imputation/run",
            json={
                "kind": "phospho",
                "method": "quantile",
                "qValue": 0.01,
                "adjustStd": 0.3,
                "seed": 1337,
                "sampleWise": False,
            },
        )
        assert imputation.status_code == 200
        assert client.get("/api/plots/phospho/options").json()["imputedAvailable"] is True

        available = client.get(
            "/api/plots/phospho/ksea-table",
            params={
                "condition1": condition1,
                "condition2": condition2,
                "dataSource": "imputed",
            },
        )
        assert available.status_code == 200


def test_reannotation_invalidates_stored_imputed_data() -> None:
    load_viewer_state(ROOT / "tests" / "fixtures" / "viewer_config.json")
    with TestClient(app) as client:
        response = client.post(
            "/api/data-tools/imputation/run",
            json={"kind": "protein", "method": "quantile", "seed": 1337},
        )
        assert response.status_code == 200
        assert client.get("/api/plots/qc/protein/options").json()["imputedAvailable"] is True

        annotation = get_annotation("protein")
        assert annotation is not None
        save_annotation(
            kind=annotation.kind,
            source_data=annotation.source_data,
            metadata=annotation.metadata,
            log2_data=annotation.log2_data,
            filtered_data=annotation.filtered_data,
            is_log2_transformed=annotation.is_log2_transformed,
            metadata_source=annotation.metadata_source,
            filter_config=annotation.filter_config,
            auto_detected=annotation.auto_detected,
            warnings=annotation.warnings,
            log2_auto_detected=annotation.log2_auto_detected,
        )

        assert client.get("/api/plots/qc/protein/options").json()["imputedAvailable"] is False
        rejected = client.get(
            "/api/plots/qc/protein/pca.png",
            params={"dataSource": "imputed", "dpi": 72},
        )
        assert rejected.status_code == 400
        assert "Run imputation successfully first" in rejected.json()["detail"]
