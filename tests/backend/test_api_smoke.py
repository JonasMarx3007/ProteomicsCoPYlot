from __future__ import annotations

import hashlib
import importlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.annotation import AnnotationFilterConfig, AnnotationImputationInfo
from app.schemas.stats import (
    AnovaRequest,
    EnrichmentRequest,
    ListEnrichmentRequest,
    VolcanoControlRequest,
)
from app.services.annotation_store import get_annotation, save_annotation
from app.services import stats_tools
from app.services.functions import impute_values_with_diagnostics
from app.services.plot_images import (
    _imputation_density_histogram_spec,
    _imputation_histogram_bin_edges,
)
from app.services.restore_state import _parse_state_blob, export_state_blob
from app.services.viewer_bootstrap import load_viewer_state


ROOT = Path(__file__).resolve().parents[2]


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
    result = load_viewer_state(ROOT / "viewer_config.json")
    loaded_datasets = {entry.rsplit(":", 1)[-1] for entry in result.loaded_datasets}
    assert {"protein", "phospho", "phosprot"} <= loaded_datasets
    assert any(entry.endswith(":WT_vs_GRK") for entry in result.loaded_annotations)


def test_report_mentions_annotation_filtering() -> None:
    load_viewer_state(ROOT / "viewer_config.json")
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
        "0.3 times the observed standard deviation."
    )
    assert imputation_text in report_html
    assert report_html.index(imputation_text) < report_html.index(
        "<strong>Data source:</strong> Imputed Data"
    )


def test_imputation_normal_fit_plot_renders_global_and_sample_wise_draws() -> None:
    load_viewer_state(ROOT / "viewer_config.json")
    with TestClient(app) as client:
        for sample_wise in ("false", "true"):
            response = client.get(
                "/api/plots/imputation/protein/overall-fit.png",
                params={
                    "qValue": 0.01,
                    "adjustStd": 0.5,
                    "seed": 1337,
                    "sampleWise": sample_wise,
                },
            )
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
            assert response.content.startswith(b"\x89PNG")

        without_draw = client.get(
            "/api/plots/imputation/protein/overall-fit.png",
            params={"showImputationDraw": "false"},
        )
        assert without_draw.status_code == 200
        assert without_draw.content.startswith(b"\x89PNG")

        for normalization in ("together", "separate"):
            after_response = client.get(
                "/api/plots/imputation/protein/after-imputation.png",
                params={"normalization": normalization},
            )
            assert after_response.status_code == 200
            assert after_response.headers["content-type"] == "image/png"
            assert after_response.headers["cache-control"].startswith("no-store")
            assert after_response.content.startswith(b"\x89PNG")

        invalid_normalization = client.get(
            "/api/plots/imputation/protein/after-imputation.png",
            params={"normalization": "invalid"},
        )
        assert invalid_normalization.status_code == 400


def _perseus_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "s1": [10.0, 12.0, np.nan, np.nan],
            "s2": [14.0, 16.0, np.nan, np.nan],
        }
    )


def test_numerical_imputation_uses_sample_sd_shift_and_width_per_sample() -> None:
    diagnostics = impute_values_with_diagnostics(
        _perseus_frame(),
        ["s1", "s2"],
        method="numerical",
        down_shift=1.8,
        width=0.3,
        seed=1337,
    )
    np.testing.assert_allclose(
        diagnostics.draw_components,
        [(11 - 1.8 * np.sqrt(2), 0.3 * np.sqrt(2), 2),
         (15 - 1.8 * np.sqrt(2), 0.3 * np.sqrt(2), 2)],
    )
    assert diagnostics.missing_before == 4
    assert diagnostics.missing_after == 0


def test_a_dataset_wide_draw_still_uses_the_pooled_distribution() -> None:
    diagnostics = impute_values_with_diagnostics(
        _perseus_frame(),
        ["s1", "s2"],
        method="numerical",
        down_shift=1.8,
        width=0.3,
        seed=1337,
        sample_wise=False,
    )
    expected_center = diagnostics.mean - 1.8 * diagnostics.std
    expected_width = 0.3 * diagnostics.std
    assert diagnostics.draw_components == [(expected_center, expected_width, 4)]
    assert diagnostics.missing_after == 0


def test_numerical_imputation_api_persists_and_renders() -> None:
    load_viewer_state(ROOT / "viewer_config.json")
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
    load_viewer_state(ROOT / "viewer_config.json")
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
    load_viewer_state(ROOT / "viewer_config.json")
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
    load_viewer_state(ROOT / "viewer_config.json")
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


def test_imputation_histogram_density_normalization_preserves_area() -> None:
    non_imputed = np.array([1.0, 2.0, 3.0, 4.0])
    imputed = np.array([0.5, 1.5])

    together_edges, together_weights = _imputation_density_histogram_spec(
        non_imputed,
        imputed,
        "together",
    )
    together_areas = [
        float(np.sum(np.histogram(values, bins=together_edges, weights=weights)[0] * np.diff(together_edges)))
        for values, weights in zip((non_imputed, imputed), together_weights, strict=True)
    ]
    assert np.isclose(sum(together_areas), 1.0)
    assert np.isclose(together_areas[0], 4 / 6)
    assert np.isclose(together_areas[1], 2 / 6)

    separate_edges, separate_weights = _imputation_density_histogram_spec(
        non_imputed,
        imputed,
        "separate",
    )
    separate_areas = [
        float(np.sum(np.histogram(values, bins=separate_edges, weights=weights)[0] * np.diff(separate_edges)))
        for values, weights in zip((non_imputed, imputed), separate_weights, strict=True)
    ]
    assert np.allclose(separate_areas, [1.0, 1.0])

    overall_edges = _imputation_histogram_bin_edges(non_imputed, imputed)
    overall_density = np.histogram(non_imputed, bins=overall_edges, density=True)[0]
    separate_non_imputed_density = np.histogram(
        non_imputed,
        bins=separate_edges,
        weights=separate_weights[0],
    )[0]
    together_non_imputed_density = np.histogram(
        non_imputed,
        bins=together_edges,
        weights=together_weights[0],
    )[0]
    assert np.array_equal(overall_edges, separate_edges)
    assert np.array_equal(overall_edges, together_edges)
    assert np.allclose(separate_non_imputed_density, overall_density)
    assert np.allclose(together_non_imputed_density, overall_density * (4 / 6))


def test_ora_uses_custom_background_and_corrects_only_tested_terms(monkeypatch) -> None:
    database = pd.DataFrame(
        {
            "ontology": ["BP", "CC", "MF"],
            "term": ["GO:1", "GO:2", "GO:3"],
            "description": ["first", "second", "third"],
            "genes": ["A;B", "C;D", "E;F"],
        }
    )
    monkeypatch.setattr(stats_tools, "load_go_db", lambda: database)

    custom = stats_tools.run_enrichment_from_list(
        ListEnrichmentRequest(
            genes=["A"],
            backgroundMode="experiment",
            backgroundGenes=["A", "B", "C"],
            minTermSize=1,
            maxTermSize=10,
            adjPValueCutoff=1.0,
        )
    )
    global_result = stats_tools.run_enrichment_from_list(
        ListEnrichmentRequest(
            genes=["A"],
            backgroundMode="global",
            minTermSize=1,
            maxTermSize=10,
            adjPValueCutoff=1.0,
        )
    )

    assert custom.backgroundMode == "experiment"
    assert custom.backgroundSize == 3
    assert custom.annotatedBackgroundSize == 3
    assert custom.testedTermCount == 2
    assert custom.terms[0].source == "BP"
    assert custom.terms[0].termId == "GO:1"
    assert len(custom.terms) == 1
    assert custom.terms[0].adjPValue == pytest.approx(custom.terms[0].pValue)
    assert custom.terms[0].adjPValue == pytest.approx(2.0 / 3.0)
    assert global_result.backgroundMode == "global"
    assert custom.terms[0].pValue > global_result.terms[0].pValue


def test_ora_rejects_missing_or_incomplete_experiment_background(monkeypatch) -> None:
    database = pd.DataFrame(
        {
            "ontology": ["BP"],
            "term": ["GO:1"],
            "description": ["first"],
            "genes": ["A;B"],
        }
    )
    monkeypatch.setattr(stats_tools, "load_go_db", lambda: database)

    with pytest.raises(ValueError, match="tested-gene background"):
        stats_tools.run_enrichment_from_list(
            ListEnrichmentRequest(genes=["A"], minTermSize=1, maxTermSize=10)
        )
    with pytest.raises(ValueError, match="Every query gene"):
        stats_tools.run_enrichment_from_list(
            ListEnrichmentRequest(
                genes=["A"],
                backgroundMode="experiment",
                backgroundGenes=["B"],
                minTermSize=1,
                maxTermSize=10,
            )
        )


def test_anova_ora_reports_its_tested_gene_background(monkeypatch) -> None:
    database = pd.DataFrame(
        {
            "ontology": ["BP"],
            "term": ["GO:1"],
            "description": ["first"],
            "genes": ["A;B"],
        }
    )
    monkeypatch.setattr(stats_tools, "load_go_db", lambda: database)
    monkeypatch.setattr(
        stats_tools,
        "_anova_cluster_genes",
        lambda payload: ("filtered", ["A"], ["A", "B"], []),
    )

    result = stats_tools.run_enrichment(
        EnrichmentRequest(
            kind="protein",
            source="anova",
            selectedCluster=1,
            backgroundMode="experiment",
            minTermSize=1,
            maxTermSize=10,
            adjPValueCutoff=1.0,
        )
    )

    assert result.backgroundGenes == ["A", "B"]
    assert result.backgroundSize == 2
    assert result.annotatedBackgroundSize == 2
    assert result.clusterTerms[0].termId == "GO:1"
    assert result.databaseSha256 == hashlib.sha256(
        database.to_csv(index=False, lineterminator="\n").encode("utf-8")
    ).hexdigest()

    global_result = stats_tools.run_enrichment(
        EnrichmentRequest(
            kind="protein",
            source="anova",
            selectedCluster=1,
            backgroundMode="global",
            minTermSize=1,
            maxTermSize=10,
            adjPValueCutoff=1.0,
        )
    )

    assert global_result.backgroundGenes == []
    assert global_result.backgroundSize == 2
    assert global_result.annotatedBackgroundSize == 2
    assert global_result.clusterTerms[0].termId == "GO:1"


def test_anova_clustering_does_not_fall_back_to_nonsignificant_rows(monkeypatch) -> None:
    anova_df = pd.DataFrame(
        {
            "GeneNames": ["A", "B"],
            "s1": [1.0, 2.0],
            "s2": [1.1, 2.1],
            "adj_pval": [0.5, 0.8],
        }
    )
    metadata = pd.DataFrame(
        {
            "sample": ["s1", "s2"],
            "condition": ["one", "two"],
        }
    )
    payload = AnovaRequest(
        kind="protein",
        source="anova_cluster",
        identifier="genes",
        pValueThreshold=0.05,
    )

    empty, _ = stats_tools._anova_cluster_dataframe(anova_df, metadata, payload)
    assert empty.empty
    assert list(empty.columns)[1] == "cluster"

    monkeypatch.setattr(
        stats_tools,
        "_anova_dataframe",
        lambda request: ("filtered", "GeneNames", anova_df, []),
    )
    monkeypatch.setattr(
        stats_tools,
        "_stats_source",
        lambda kind, data_source="data": ("filtered", anova_df, metadata, []),
    )
    response = stats_tools.run_anova(payload)
    assert response.significantCount == 0
    assert response.clusterCount == 0
    assert response.clusterRows == []
    assert "clustering was not run" in response.warnings[-1]

    figure, plt = stats_tools._anova_heatmap_figure(
        anova_df,
        metadata,
        kind="protein",
        advanced=None,
        label_column="GeneNames",
        p_value_threshold=0.05,
        clustered=False,
        show_dendrograms=True,
        show_legend=True,
    )
    assert not any(axis.images for axis in figure.axes)
    assert any("No rows passed" in text.get_text() for axis in figure.axes for text in axis.texts)
    plt.close(figure)

    anova_df.loc[0, "adj_pval"] = 0.01
    one, _ = stats_tools._anova_cluster_dataframe(anova_df, metadata, payload)
    assert one["GeneNames"].tolist() == ["A"]
    assert one["cluster"].tolist() == [1]


def test_anova_clustering_preserves_small_clusters_and_ignores_raw_label_numbers(monkeypatch) -> None:
    row_count = 21
    anova_df = pd.DataFrame(
        {
            "GeneNames": [f"G{index}" for index in range(row_count)],
            "s1": np.linspace(0.0, 2.0, row_count),
            "s2": np.linspace(2.0, 0.0, row_count),
            "adj_pval": np.full(row_count, 0.01),
        }
    )
    metadata = pd.DataFrame({"sample": ["s1", "s2"], "condition": ["one", "two"]})
    payload = AnovaRequest(
        kind="protein",
        source="anova_cluster",
        identifier="genes",
        pValueThreshold=0.05,
        nClusters=3,
    )

    monkeypatch.setattr(stats_tools, "linkage", lambda *args, **kwargs: object())
    monkeypatch.setattr(stats_tools, "leaves_list", lambda hierarchy: np.arange(row_count))

    first_labels = np.asarray([10] * 10 + [77] + [500] * 10)
    monkeypatch.setattr(stats_tools, "fcluster", lambda *args, **kwargs: first_labels.copy())
    first, _ = stats_tools._anova_cluster_dataframe(anova_df, metadata, payload)

    second_labels = np.asarray([900] * 10 + [2] + [41] * 10)
    monkeypatch.setattr(stats_tools, "fcluster", lambda *args, **kwargs: second_labels.copy())
    second, _ = stats_tools._anova_cluster_dataframe(anova_df, metadata, payload)

    assert first.groupby("cluster").size().sort_values().tolist() == [1, 10, 10]
    assert second.groupby("cluster").size().sort_values().tolist() == [1, 10, 10]
    assert first.set_index("GeneNames")["cluster"].to_dict() == second.set_index("GeneNames")["cluster"].to_dict()


def test_pathway_gene_aggregation_is_median_based_exact_and_order_invariant() -> None:
    frame = pd.DataFrame(
        {
            "GeneNames": [
                "AKT1; MAPK1",
                "AKT1",
                "AKT1;AKT1",
                "AKT10",
                "MAPK1",
                "EMPTY",
                "ZERO",
            ],
            "s1": [2.0, 100.0, 4.0, -1000.0, 8.0, np.inf, 0.0],
            "s2": [0.0, 4.0, np.nan, 10.0, 6.0, np.nan, 0.0],
        }
    )
    pathway_genes = ["AKT1", "akt1", "AKT10", "MAPK1", "EMPTY", "ZERO", "MISSING"]

    aggregated, counts = stats_tools._aggregate_pathway_gene_values(
        frame,
        gene_column="GeneNames",
        sample_columns=["s1", "s2"],
        pathway_genes=pathway_genes,
    )
    shuffled, shuffled_counts = stats_tools._aggregate_pathway_gene_values(
        frame.sample(frac=1.0, random_state=19).reset_index(drop=True),
        gene_column="GeneNames",
        sample_columns=["s1", "s2"],
        pathway_genes=pathway_genes,
    )

    assert aggregated.index.tolist() == ["AKT1", "AKT10", "MAPK1", "EMPTY", "ZERO", "MISSING"]
    assert aggregated.loc["AKT1"].tolist() == [4.0, 2.0]
    assert aggregated.loc["AKT10"].tolist() == [-1000.0, 10.0]
    assert aggregated.loc["MAPK1"].tolist() == [5.0, 3.0]
    assert aggregated.loc["ZERO"].tolist() == [0.0, 0.0]
    assert aggregated.loc["EMPTY"].isna().all()
    assert aggregated.loc["MISSING"].isna().all()
    assert counts.to_dict() == {
        "AKT1": 3,
        "AKT10": 1,
        "MAPK1": 2,
        "EMPTY": 1,
        "ZERO": 1,
        "MISSING": 0,
    }
    pd.testing.assert_frame_equal(aggregated, shuffled)
    pd.testing.assert_series_equal(counts, shuffled_counts)


def test_pathway_heatmap_labels_show_source_feature_counts(monkeypatch) -> None:
    frame = pd.DataFrame(
        {
            "GeneNames": ["AKT1", "AKT1", "AKT10"],
            "s1": [2.0, 4.0, 9.0],
            "s2": [3.0, 5.0, 10.0],
        }
    )
    metadata = pd.DataFrame(
        {"sample": ["s1", "s2"], "condition": ["one", "two"]}
    )
    monkeypatch.setattr(
        stats_tools,
        "_stats_source",
        lambda kind, data_source="data": ("data", frame, metadata, []),
    )
    monkeypatch.setattr(
        stats_tools,
        "load_go_db",
        lambda: pd.DataFrame(
            {"description": ["Test pathway"], "genes": ["AKT1;AKT10"]}
        ),
    )
    captured: dict[str, object] = {}

    def capture_figure(figure, plt, dpi):
        captured["labels"] = [label.get_text() for label in figure.axes[0].get_yticklabels()]
        captured["title"] = figure.axes[0].get_title()
        plt.close(figure)
        return b"png"

    monkeypatch.setattr(stats_tools, "_to_png_bytes", capture_figure)

    def render(**overrides):
        return stats_tools.pathway_heatmap_png(
            kind="protein",
            pathway="Test pathway",
            conditions=[],
            value_type="log2",
            include_id=False,
            header=True,
            remove_empty=True,
            cluster_rows=False,
            cluster_cols=False,
            width_cm=20,
            height_cm=12,
            dpi=150,
            **overrides,
        )

    # Off by default: on a real pathway the counts are forty parentheticals down
    # the side of the figure, and most of them read 1.
    assert render() == b"png"
    assert captured["labels"] == ["AKT1", "AKT10"]

    assert render(show_source_count=True) == b"png"
    assert captured["labels"] == ["AKT1 (n=2)", "AKT10 (n=1)"]
    assert "median across mapped features" in str(captured["title"])


def test_phosprot_ora_uses_all_gene_group_tokens(monkeypatch) -> None:
    frame = pd.DataFrame(
        {
            "Gene_group": [" A ; B ; A ;;", "B; C", np.nan, "D;; E"],
            "GeneNames": ["WRONG1", "WRONG2", "WRONG3", "WRONG4"],
            "significance": ["Upregulated", "Downregulated", "Not significant", "Not significant"],
        }
    )
    monkeypatch.setattr(
        stats_tools,
        "_volcano_dataframe",
        lambda **kwargs: ("filtered", "Gene_group", frame, []),
    )

    _, up, down, background, _ = stats_tools._different_genes(
        EnrichmentRequest(
            kind="phosprot",
            source="volcano",
            dataSource="data",
            condition1="one",
            condition2="two",
            pValueThreshold=0.05,
            log2fcThreshold=1.0,
            testType="unpaired",
            useUncorrected=False,
        )
    )

    assert up == ["A", "B"]
    assert down == ["B", "C"]
    assert background == ["A", "B", "C", "D", "E"]
    assert "nan" not in background


@pytest.mark.parametrize("use_uncorrected", [False, True])
def test_control_ora_uses_exact_control_volcano_output(
    monkeypatch,
    use_uncorrected: bool,
) -> None:
    frame = pd.DataFrame(
        {
            "GeneNames": ["UP", "DOWN", "NONE"],
            "significance": ["Upregulated", "Downregulated", "Not significant"],
            "correction": [
                "none (uncorrected)" if use_uncorrected else "Benjamini-Hochberg"
            ] * 3,
        }
    )

    def fake_volcano_dataframe(**kwargs):
        assert kwargs["condition1_control"] == "control-one"
        assert kwargs["condition2_control"] == "control-two"
        assert kwargs["use_uncorrected"] is use_uncorrected
        return "filtered", "GeneNames", frame, ["shared warning"]

    monkeypatch.setattr(stats_tools, "_volcano_dataframe", fake_volcano_dataframe)
    tab_result = stats_tools.run_volcano_control(
        VolcanoControlRequest(
            kind="protein",
            condition1="one",
            condition2="two",
            condition1Control="control-one",
            condition2Control="control-two",
            identifier="genes",
            useUncorrected=use_uncorrected,
        )
    )
    source, up, down, background, warnings = stats_tools._different_genes(
        EnrichmentRequest(
            kind="protein",
            source="volcano_control",
            condition1="one",
            condition2="two",
            condition1Control="control-one",
            condition2Control="control-two",
            useUncorrected=use_uncorrected,
        )
    )

    tab_frame = pd.DataFrame(tab_result.rows)
    assert source == tab_result.sourceUsed
    assert up == tab_frame.loc[tab_frame["significance"] == "Upregulated", "GeneNames"].tolist()
    assert down == tab_frame.loc[tab_frame["significance"] == "Downregulated", "GeneNames"].tolist()
    assert background == sorted(tab_frame["GeneNames"].tolist())
    assert tab_frame["correction"].unique().tolist() == [
        "none (uncorrected)" if use_uncorrected else "Benjamini-Hochberg"
    ]
    assert warnings == tab_result.warnings


def test_ora_bh_denominator_is_the_number_of_tested_terms(monkeypatch) -> None:
    from scipy.stats import hypergeom

    from app.services.runtime_cache import invalidate_runtime_cache

    background = [f"G{i}" for i in range(60)]
    query = ["G0", "G1", "G2", "G3"]
    coverage = {
        "ontology": "BP",
        "term": "GO:all",
        "description": "coverage",
        "genes": ";".join(background),
    }
    real = {"ontology": "BP", "term": "GO:1", "description": "real", "genes": "G0;G1;G2;G8;G9"}

    def _run(padding: int):
        invalidate_runtime_cache(f"ora-denominator-guard-{padding}")
        rows = [coverage, real] + [
            {
                "ontology": "BP",
                "term": f"GO:pad{i}",
                "description": f"pad {i}",
                "genes": ";".join(background[40:48]),
            }
            for i in range(padding)
        ]
        monkeypatch.setattr(stats_tools, "load_go_db", lambda: pd.DataFrame(rows))
        return stats_tools.run_enrichment_from_list(
            ListEnrichmentRequest(
                genes=query,
                backgroundMode="experiment",
                backgroundGenes=background,
                minTermSize=1,
                maxTermSize=50,
                adjPValueCutoff=1.0,
            )
        )

    none_added = _run(0)
    many_added = _run(400)
    reported = [term for term in none_added.terms if term.termId == "GO:1"][0]
    padded = [term for term in many_added.terms if term.termId == "GO:1"][0]

    assert none_added.testedTermCount == 1
    assert many_added.testedTermCount == 401
    assert reported.adjPValue == pytest.approx(padded.adjPValue)
    expected = float(hypergeom.sf(2, 60, 5, 4))
    assert reported.pValue == pytest.approx(expected)
    assert reported.adjPValue == pytest.approx(expected)
    assert not np.isclose(padded.adjPValue, 1.0), "padding must not saturate the correction"
