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


ROOT = Path(__file__).resolve().parents[3]
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
    # The wheel ships only the GO table, so it gets the notice written for it alone.
    assert '"PACKAGED_README.md"' in setup_text
    manifest_text = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    assert "data/db/README.md" in manifest_text
    assert "data/db/PACKAGED_README.md" in manifest_text
    assert Path(sys.prefix).is_dir()


def test_packaged_go_notice_states_the_shipped_file_checksum() -> None:
    import hashlib

    digest = hashlib.sha256((ROOT / "data" / "db" / "all_go_terms_genes.csv").read_bytes()).hexdigest()
    packaged = (ROOT / "data" / "db" / "PACKAGED_README.md").read_text(encoding="utf-8")
    repository = (ROOT / "data" / "db" / "README.md").read_text(encoding="utf-8")
    assert digest in packaged and digest in repository
    for other in ("BioNamesDB.txt", ".fasta"):
        assert other not in packaged


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
    # Each label names its GO ontology since 2026-10-02.
    assert {"term one (BP)", "term three (BP)"} <= labels


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
    # log2FC is condition1 - condition2, so the directions are the mirror of
    # what "two" being higher used to produce.
    assert result["Upregulated"] == ["B", "C"]
    assert result["Downregulated"] == ["A", "B"]
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
    assert fallback["Upregulated"] == ["B", "C"]
    assert fallback["Downregulated"] == ["A", "B"]
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
    configs = [ROOT / "viewer_config.json", ROOT / "viewer_data" / "HEK293" / "viewer_config.json",
               ROOT / "tests" / "fixtures" / "viewer_config.json"]
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


# --- every plotting function returns its figure ---------------------------------
#
# A notebook line reads `fig = plot(...)`, and that has to bind something.
# `sty_plot` called `plt.show()` and returned None, so the example notebook's own
# `fig = sty_plot(data3)` bound nothing: the figure could not be saved, resized,
# or put into a report from a script, and only appeared at all because Jupyter
# draws whatever matplotlib has open. The tests below call every plotting
# function of the pip package on a small synthetic project and check that what
# comes back is the figure it drew.

PLOT_SAMPLES = ["A1", "A2", "A3", "B1", "B2", "B3"]
PLOT_GENES = ["TP53", "BRCA1", "EGFR", "AKT1", "MAPK1"]


@pytest.fixture(scope="module")
def plot_inputs(tmp_path_factory) -> dict:
    """Protein, phosphosite, phosphoprotein and peptide inputs, small but valid."""
    pd = notebook_functions.pd
    np = notebook_functions.np
    rng = np.random.default_rng(5)
    n = 60
    values = rng.normal(20, 2, (n, len(PLOT_SAMPLES)))
    values[:15, 3:] += 4  # a block of clearly regulated rows for ANOVA and volcanoes
    values[20, 0] = np.nan
    values[21, 4] = np.nan
    meta = pd.DataFrame({"sample": PLOT_SAMPLES, "condition": ["A"] * 3 + ["B"] * 3})
    genes = PLOT_GENES + [f"G{i}" for i in range(len(PLOT_GENES), n)]
    protein = pd.DataFrame(values, columns=PLOT_SAMPLES)
    protein.insert(0, "ProteinNames", [f"P{i}" for i in range(n)])
    protein.insert(1, "GeneNames", genes)

    phospho = protein.drop(columns=["ProteinNames"]).assign(
        PTM_Collapse_key=[f"P{i}~S{10 + i}_M1" for i in range(n)],
        Protein_group=[f"P{i}" for i in range(n)],
        Gene_group=genes,
        PTM_localization=[0.99, 0.5, 0.8] * (n // 3),
        UPD_seq=[f"PEPS*TIDE{i}" for i in range(n)],
        site_num=1,
    )
    phosprot = pd.DataFrame({"Phosphoprotein": [f"P{i}" for i in range(n)], "site_num": [1, 2, 3] * (n // 3)})

    sequences = ["AKR", "PEPTIDEK", "MPEPRK", "ARPK", "PEPM(UniMod:35)TIDE"]
    peptide_path = tmp_path_factory.mktemp("peptides") / "peptides.tsv"
    pd.DataFrame([
        {
            "File.Name": sample, "Run": sample,
            "Stripped.Sequence": sequence.replace("(UniMod:35)", ""),
            "Modified.Sequence": sequence, "Precursor.Id": sequence + "2",
            "Precursor.Quantity": float(i + 1), "RT": float(10 + i), "Predicted.RT": float(11 + i),
            "Protein.Group": "P1", "Genes": "TP53",
        }
        for sample in PLOT_SAMPLES for i, sequence in enumerate(sequences)
    ]).to_csv(peptide_path, sep="\t", index=False)

    go_db = pd.DataFrame({
        "ontology": ["BP", "BP"], "term": ["GO:1", "GO:2"],
        "description": ["term one", "term two"],
        "genes": ["TP53;BRCA1;EGFR", "AKT1;MAPK1;TP53"],
    })
    ksea = pd.DataFrame({"Kinase": ["K"], "Log2(Frequency Factor)": [1.0], "Adjusted p-value": [0.01]})
    return {
        "protein": protein, "linear": protein.assign(**{c: 2 ** protein[c] for c in PLOT_SAMPLES}),
        "meta": meta, "phospho": phospho, "phosprot": phosprot, "peptides": str(peptide_path),
        "go_db": go_db, "genes": genes, "ksea": ksea,
    }


def _plot_calls(nb, inputs: dict) -> dict:
    """One call per plotting function, keyed by the function's name."""
    data, meta, phospho, peptides = inputs["protein"], inputs["meta"], inputs["phospho"], inputs["peptides"]
    anova = nb.anova_data_f(data, meta)
    volcano = nb.volcano_data_f(data, meta, "A", "B")
    ksea = inputs["ksea"]
    return {
        "qqnorm_plot": lambda: nb.qqnorm_plot(data, meta),
        "impute_values": lambda: nb.impute_values(data, meta, ret=1),
        "coverage_plot": lambda: nb.coverage_plot(data, meta),
        "coverage_plot_summary": lambda: nb.coverage_plot_summary(data, meta),
        "coverage_plot_pep": lambda: nb.coverage_plot_pep(peptides, meta),
        "histo_int": lambda: nb.histo_int(data, meta),
        "boxplot_int": lambda: nb.boxplot_int(data, meta),
        "boxplot_int_single": lambda: nb.boxplot_int_single(data, meta),
        "cov_plot": lambda: nb.cov_plot(inputs["linear"], meta, data_scale="linear"),
        "pca_plot": lambda: nb.pca_plot(data, meta),
        "pca_plot_interactive": lambda: nb.pca_plot_interactive(data, meta),
        "abundance_plot": lambda: nb.abundance_plot(data, meta),
        "interactive_abundance_plot": lambda: nb.interactive_abundance_plot(data, meta, "A"),
        "corr_plot": lambda: nb.corr_plot(data, meta),
        "volcano_plot": lambda: nb.volcano_plot(volcano, "A", "B"),
        "volcano_plot_h": lambda: nb.volcano_plot_h(volcano, "A", "B"),
        "volcano_plot_sim": lambda: nb.volcano_plot_sim(data, meta, "A", "B"),
        "anova_plot": lambda: nb.anova_plot(anova, meta),
        "anova_plot_cluster": lambda: nb.anova_plot_cluster(nb.anova_cluster_data(anova, meta, n_clusters=2), meta),
        "enrichment_analysis": lambda: nb.enrichment_analysis(
            PLOT_GENES[:3], min_num=1, max_num=10, background=inputs["genes"], adj_p_value_cutoff=1.0),
        "proteins_in_pathway": lambda: nb.proteins_in_pathway(data, meta, inputs["go_db"], "term one"),
        "phosprot_regulation": lambda: nb.phosprot_regulation(phospho, meta, "A", "B"),
        "rt_vs_pred_rt_plot": lambda: nb.rt_vs_pred_rt_plot(peptides, bins=10),
        "modification_plot": lambda: nb.modification_plot(peptides, meta),
        "missed_cleavage_plot": lambda: nb.missed_cleavage_plot(peptides, meta),
        "compare_prot_line": lambda: nb.compare_prot_line(data, meta, ["A", "B"], ["P1"]),
        "boxplot_int_single_prot": lambda: nb.boxplot_int_single_prot(data, meta, "P1"),
        "phossite_on_prot_regulation": lambda: nb.phossite_on_prot_regulation(phospho, meta, "P1"),
        "phossite_coverage_plot": lambda: nb.phossite_coverage_plot(phospho, meta),
        "phossite_coverage_plot_summary": lambda: nb.phossite_coverage_plot_summary(phospho, meta),
        "sty_plot": lambda: nb.sty_plot(phospho),
        "simple_phos_site_plot": lambda: nb.simple_phos_site_plot(phospho),
        "phossite_dist": lambda: nb.phossite_dist(inputs["phosprot"]),
        "kinase_library_volcano": lambda: nb.kinase_library_volcano(ksea, ksea.assign(Kinase=["L"])),
        "correlation_xy_intensity_single": lambda: nb.correlation_xy_intensity_single(data, "A1", "B1"),
        "correlation_xy_intensity": lambda: nb.correlation_xy_intensity(data, meta, "A", "B"),
        "overlap_plot_single": lambda: nb.overlap_plot_single(data, "A1", "B1"),
        "overlap_plot_condition": lambda: nb.overlap_plot_condition(data, meta, "A", "B"),
        "missing_value_plot": lambda: nb.missing_value_plot(data, meta),
        "missing_value_plot_prec": lambda: nb.missing_value_plot_prec(peptides, meta),
        "missing_value_plot_pep": lambda: nb.missing_value_plot_pep(peptides, meta),
        "missing_value_heatmap": lambda: nb.missing_value_heatmap(data, meta),
    }


# The KSEA names are aliases of the Kinase Library functions, not functions of
# their own, so calling the target covers them.
PLOT_ALIASES = {"ksea_volcano": "kinase_library_volcano"}


def test_the_plotting_calls_cover_every_function_named_as_a_plot(plot_inputs, monkeypatch) -> None:
    """A new `*plot*` function has to be added to the calls above to be checked.

    Listed from the imported module, not from its source text.
    """
    import inspect

    monkeypatch.setattr(notebook_functions, "load_go_db", lambda: plot_inputs["go_db"])
    calls = _plot_calls(notebook_functions, plot_inputs)
    public = {
        name for name, value in vars(notebook_functions).items()
        if inspect.isfunction(value) and value.__module__ == notebook_functions.__name__
        and not name.startswith("_")
    }
    named_as_plots = {name for name in public if "plot" in name} - set(PLOT_ALIASES)
    assert not named_as_plots - set(calls), sorted(named_as_plots - set(calls))
    assert not set(calls) - public, f"calls for functions that no longer exist: {sorted(set(calls) - public)}"


def test_every_plotting_function_returns_its_figure(plot_inputs, monkeypatch) -> None:
    import warnings

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from plotly.graph_objects import Figure as PlotlyFigure

    monkeypatch.setattr(notebook_functions, "load_go_db", lambda: plot_inputs["go_db"])
    offenders = []
    for name, call in _plot_calls(notebook_functions, plot_inputs).items():
        plt.close("all")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = call()
        if isinstance(result, Figure):
            drew = bool(result.axes)
        elif isinstance(result, PlotlyFigure):
            drew = bool(result.data) or bool(result.layout.annotations)
        else:
            drew = False
        if not drew:
            offenders.append(f"{name} -> {type(result).__name__}")
        plt.close("all")

    assert offenders == [], (
        "these plotting functions draw a figure and do not return it, so "
        f"`fig = f(...)` binds something else: {offenders}"
    )


def test_the_plotting_functions_run_with_the_repository_hidden(plot_inputs, monkeypatch) -> None:
    """The imports a function makes only when called are checked by calling it.

    Every top-level name the pip package must never import -- the web app, the
    repository's other folders -- is made unimportable for the duration, and
    every plotting function is run. A function-level `from app... import`
    raises here; the module-level imports are checked in a fresh interpreter by
    test_pip_package_is_standalone.
    """
    import warnings

    import matplotlib.pyplot as plt

    forbidden = ("app", "backend", "tests", "frontend", "proteomics_backend")
    for name in list(sys.modules):
        if name.split(".")[0] in forbidden:
            monkeypatch.setitem(sys.modules, name, None)
    for name in forbidden:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setattr(notebook_functions, "load_go_db", lambda: plot_inputs["go_db"])

    for name, call in _plot_calls(notebook_functions, plot_inputs).items():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                call()
            except ImportError as exc:
                raise AssertionError(f"{name} imports from the repository when called: {exc}") from exc
        plt.close("all")
