from __future__ import annotations

import json
import sys
from importlib import resources
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import proteomicscopylot
import pytest
from proteomicscopylot import notebook_functions


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DATA = {
    "20260511_144120_20240822_JM_HEK293_WP_Report_PG.tsv",
    "20260511_144129_20240822_JM_HEK293_PP_Report_collapsed.tsv",
    "phospho_metadata_full.csv",
    "phosprot_filtered_data_full.csv",
    "protein_metadata_full.csv",
}


def test_python_and_r_notebook_helpers_are_exposed() -> None:
    assert proteomicscopylot.__version__
    assert callable(notebook_functions.read_data)
    assert (ROOT / "proteomicscopylot" / "notebook_functions.R").is_file()


def test_go_database_is_available_to_source_and_wheel_builds() -> None:
    assert (ROOT / "data" / "db" / "all_go_terms_genes.csv").is_file()
    assert (ROOT / "data" / "db" / "README.md").is_file()
    setup_text = (ROOT / "setup.py").read_text(encoding="utf-8")
    assert "all_go_terms_genes.csv" in setup_text
    assert '"README.md"' in setup_text
    manifest_text = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "data/db/README.md" in manifest_text
    assert Path(sys.prefix).is_dir()


def test_ora_requires_an_explicit_experiment_background(monkeypatch) -> None:
    database = notebook_functions.pd.DataFrame(
        {
            "ontology": ["BP", "BP", "BP"],
            "term": ["GO:1", "GO:2", "GO:3"],
            "description": ["term one", "term two", "term three"],
            "genes": ["TP53;BRCA1", "EGFR", "BRCA1"],
        }
    )
    monkeypatch.setattr(notebook_functions, "load_go_db", lambda: database)

    with pytest.raises(ValueError, match="tested-gene background"):
        notebook_functions.enrichment_analysis(["TP53"])
    figure = notebook_functions.enrichment_analysis(
        ["TP53"],
        min_num=1,
        max_num=10,
        background=["TP53", "BRCA1", "EGFR"],
        adj_p_value_cutoff=1.0,
    )
    assert figure is not None
    assert figure.axes[0].get_title().startswith("GO Enrichment (ORA)")
    grouped_figure = notebook_functions.enrichment_analysis(
        ["TP53;BRCA1"],
        min_num=1,
        max_num=10,
        background=["TP53;BRCA1", "EGFR"],
        adj_p_value_cutoff=1.0,
        workflow="Phosphoprotein",
    )
    assert grouped_figure is not None
    labels = {label.get_text() for label in grouped_figure.axes[0].get_yticklabels()}
    assert {"term one", "term three"} <= labels


def test_notebook_anova_clustering_requires_significant_rows() -> None:
    anova_df = notebook_functions.pd.DataFrame(
        {
            "GeneNames": ["A", "B"],
            "s1": [1.0, 2.0],
            "s2": [1.1, 2.1],
            "adj_pval": [0.5, 0.8],
        }
    )
    metadata = notebook_functions.pd.DataFrame(
        {"sample": ["s1", "s2"], "condition": ["one", "two"]}
    )

    empty = notebook_functions.anova_cluster_data(anova_df, metadata)
    assert empty.empty
    assert "cluster" in empty.columns

    figure = notebook_functions.anova_plot(anova_df, metadata)
    assert not any(axis.images for axis in figure.axes)
    assert any("No rows passed" in text.get_text() for axis in figure.axes for text in axis.texts)

    all_rows = notebook_functions.anova_cluster_data(
        anova_df,
        metadata,
        only_significant=False,
        n_clusters=2,
    )
    assert len(all_rows) == 2

    anova_df.loc[0, "adj_pval"] = 0.01
    one = notebook_functions.anova_cluster_data(anova_df, metadata)
    assert one["GeneNames"].tolist() == ["A"]
    assert one["cluster"].tolist() == [1]


def test_notebook_anova_clustering_preserves_a_singleton_cluster() -> None:
    offsets = notebook_functions.np.linspace(-0.05, 0.05, 20)
    group_one = notebook_functions.np.column_stack(
        [offsets, offsets, offsets, 3 + offsets, 3 + offsets, 3 + offsets]
    )
    group_two = notebook_functions.np.column_stack(
        [3 + offsets, 3 + offsets, 3 + offsets, offsets, offsets, offsets]
    )
    singleton = notebook_functions.np.asarray([[0.0, 3.0, 0.0, 3.0, 0.0, 3.0]])
    matrix = notebook_functions.np.vstack([group_one, singleton, group_two])
    sample_columns = [f"s{index}" for index in range(1, 7)]
    anova_df = notebook_functions.pd.DataFrame(matrix, columns=sample_columns)
    anova_df.insert(0, "GeneNames", [f"G{index}" for index in range(len(anova_df))])
    anova_df["adj_pval"] = 0.01
    metadata = notebook_functions.pd.DataFrame(
        {"sample": sample_columns, "condition": ["one"] * 3 + ["two"] * 3}
    )

    clustered = notebook_functions.anova_cluster_data(anova_df, metadata, n_clusters=3)
    shuffled = notebook_functions.anova_cluster_data(
        anova_df.sample(frac=1.0, random_state=17),
        metadata,
        n_clusters=3,
    )

    def membership_partition(frame):
        return {
            frozenset(group["GeneNames"].tolist())
            for _, group in frame.groupby("cluster")
        }

    assert clustered["cluster"].nunique() == 3
    assert clustered.groupby("cluster").size().sort_values().tolist() == [1, 20, 20]
    assert membership_partition(clustered) == membership_partition(shuffled)


def test_python_pathway_heatmap_aggregation_is_order_invariant() -> None:
    frame = notebook_functions.pd.DataFrame(
        {
            "GeneNames": ["AKT1; MAPK1", "AKT1", "AKT1;AKT1", "AKT10", "ZERO"],
            "s1": [2.0, 100.0, 4.0, -1000.0, 0.0],
            "s2": [0.0, 4.0, notebook_functions.np.nan, 10.0, 0.0],
        }
    )
    genes = ["AKT1", "akt1", "AKT10", "ZERO", "MISSING"]

    aggregated, counts = notebook_functions._aggregate_pathway_gene_values(
        frame,
        "GeneNames",
        ["s1", "s2"],
        genes,
    )
    shuffled, shuffled_counts = notebook_functions._aggregate_pathway_gene_values(
        frame.sample(frac=1.0, random_state=23).reset_index(drop=True),
        "GeneNames",
        ["s1", "s2"],
        genes,
    )

    assert aggregated.index.tolist() == ["AKT1", "AKT10", "ZERO", "MISSING"]
    assert aggregated.loc["AKT1"].tolist() == [4.0, 2.0]
    assert aggregated.loc["AKT10"].tolist() == [-1000.0, 10.0]
    assert aggregated.loc["ZERO"].tolist() == [0.0, 0.0]
    assert aggregated.loc["MISSING"].isna().all()
    assert counts.to_dict() == {"AKT1": 3, "AKT10": 1, "ZERO": 1, "MISSING": 0}
    notebook_functions.pd.testing.assert_frame_equal(aggregated, shuffled)
    notebook_functions.pd.testing.assert_series_equal(counts, shuffled_counts)


def test_python_phosphoproteome_different_genes_uses_all_group_tokens() -> None:
    metadata = notebook_functions.pd.DataFrame(
        {
            "sample": ["a1", "a2", "b1", "b2"],
            "condition": ["one", "one", "two", "two"],
        }
    )
    data = notebook_functions.pd.DataFrame(
        {
            "Gene_group": [" A ; B ; A ;;", "B; C", notebook_functions.np.nan, "D;; E"],
            "GeneNames": ["WRONG1", "WRONG2", "WRONG3", "WRONG4"],
            "a1": [1.0, 10.0, 2.0, 1.0],
            "a2": [1.2, 10.3, 2.2, 2.0],
            "b1": [10.0, 1.0, 2.0, 1.0],
            "b2": [10.3, 1.2, 2.2, 2.0],
        }
    )

    result = notebook_functions.different_genes(
        data,
        metadata,
        "one",
        "two",
        in_pval=0.05,
        in_log2fc=1,
        workflow="Phosphoprotein",
        uncorrected=True,
    )
    assert result["Upregulated"] == ["A", "B"]
    assert result["Downregulated"] == ["B", "C"]
    assert result["Background"] == ["A", "B", "C", "D", "E"]

    fallback = notebook_functions.different_genes(
        data.drop(columns=["Gene_group"]).assign(GeneNames=["A; B", "B; C", None, "D; E"]),
        metadata,
        "one",
        "two",
        in_pval=0.05,
        in_log2fc=1,
        workflow="Phosphoprotein",
        uncorrected=True,
    )
    assert fallback["Upregulated"] == ["A", "B"]
    assert fallback["Downregulated"] == ["B", "C"]
    assert fallback["Background"] == ["A", "B", "C", "D", "E"]

    anova_input = data.assign(Phosphoprotein=["P1", "P2", "P3", "P4"])
    anova_result = notebook_functions.anova_data_f(
        anova_input,
        metadata,
        workflow="Phosphoprotein",
        uncorrected=True,
    )
    assert "Gene_group" in anova_result.columns
    assert notebook_functions._different_gene_tokens(anova_result["Gene_group"], True) == [
        "A",
        "B",
        "C",
        "D",
        "E",
    ]


def test_notebook_anova_rejects_no_testable_rows() -> None:
    metadata = notebook_functions.pd.DataFrame(
        {
            "sample": ["a1", "a2", "b1", "b2"],
            "condition": ["one", "one", "two", "two"],
        }
    )
    data = notebook_functions.pd.DataFrame(
        {
            "ProteinNames": ["P1"],
            "a1": [1.0],
            "a2": [notebook_functions.np.nan],
            "b1": [2.0],
            "b2": [notebook_functions.np.nan],
        }
    )
    with pytest.raises(ValueError, match="No rows have enough replicate values for ANOVA"):
        notebook_functions.anova_data_f(data, metadata)


def test_optional_sequence_function_reports_the_missing_dependency(monkeypatch) -> None:
    monkeypatch.setattr(notebook_functions, "SeqIO", None)
    with pytest.raises(ModuleNotFoundError, match="biopython"):
        notebook_functions.fasta_to_dataframe("proteins.fasta")


def test_canonical_example_data_is_complete_and_not_duplicated() -> None:
    package_data = resources.files("proteomicscopylot.example_data")
    assert EXPECTED_DATA <= {entry.name for entry in package_data.iterdir()}
    assert not (ROOT / "example_data").exists()


def test_viewer_configs_resolve_to_canonical_example_data() -> None:
    configs = [ROOT / "viewer_config.json", ROOT / "viewer_data" / "HEK293" / "viewer_config.json"]
    for config_path in configs:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        dataset = payload["datasets"]["HEK293"]
        paths = [dataset["protein_file"], dataset["phospho_file"], dataset["phosprot_file"]]
        profile = dataset["metadata_profiles"]["WT_vs_GRK"]
        paths.extend([profile["meta_file"], profile["meta_phospho_file"]])
        for relative in paths:
            resolved = (config_path.parent / relative).resolve()
            assert resolved.is_file(), f"Missing configured example asset: {resolved}"
            assert ROOT / "proteomicscopylot" / "example_data" in resolved.parents
