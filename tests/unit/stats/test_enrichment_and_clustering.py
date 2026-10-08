"""ORA backgrounds and correction, ANOVA clustering and pathway aggregation.

Moved out of test_api_smoke.py (2026-10-02)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.schemas.stats import (
    AnovaRequest,
    EnrichmentRequest,
    ListEnrichmentRequest,
    VolcanoControlRequest,
)
from app.services import stats_tools


ROOT = Path(__file__).resolve().parents[3]




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
