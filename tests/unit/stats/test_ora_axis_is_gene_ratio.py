"""The ORA dot plot's x axis is GeneRatio (overlap / query genes).

That is the quantity clusterProfiler's dot plot uses, so a reader used to those
figures reads this one without a legend. The plot used to put overlap / term
size ("Hits (%)") there, which looks the same and means something else. Term
coverage is still reported, in the table, as hitPercent.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]

from app.services import stats_tools
from proteomicscopylot import notebook_functions


def test_backend_terms_carry_gene_ratio_and_term_coverage() -> None:
    background, eligible = stats_tools._prepare_ora_universe(None, 5, 500)
    query = sorted(eligible[0][3])[:15] + sorted(eligible[1][3])[:5]
    terms = stats_tools._enrichment_terms(query, 5, None, background, eligible)
    assert terms
    query_in_background = len(set(query) & background)
    for term in terms:
        assert term.querySize == query_in_background
        assert np.isclose(term.geneRatio, term.intersectionSize / query_in_background)
        assert np.isclose(term.hitPercent, term.intersectionSize / term.termSize * 100)


def test_backend_dot_plot_x_is_gene_ratio(monkeypatch) -> None:
    from app.schemas.stats import EnrichmentRequest, EnrichmentResultResponse, EnrichmentTerm

    terms = [
        EnrichmentTerm(source="GO:BP", termId=f"GO:{i:07d}", name=f"term {i}", termSize=100 + i,
                       intersectionSize=2 + i, querySize=30, geneRatio=(2 + i) / 30,
                       hitPercent=(2 + i) / (100 + i) * 100, pValue=10.0 ** -(i + 2),
                       adjPValue=10.0 ** -(i + 1), intersectingGenes=["G"])
        for i in range(4)
    ]
    result = EnrichmentResultResponse(kind="protein", sourceUsed="data", upTerms=terms, downTerms=[],
                                      backgroundMode="experiment", backgroundGenes=[], backgroundSize=30,
                                      annotatedBackgroundSize=30, organism="Homo sapiens",
                                      databaseSha256="x", testedTermCount=4, termCounts={},
                                      upstreamCorrectionMethod="Benjamini-Hochberg", warnings=[])
    monkeypatch.setattr(stats_tools, "run_enrichment", lambda payload: result)
    captured = {}

    def capture(fig, plt, **kwargs):
        captured["ax"] = fig.axes[0]
        return b"\x89PNG\r\n\x1a\n"

    monkeypatch.setattr(stats_tools, "_to_png_bytes", capture)
    payload = EnrichmentRequest(kind="protein", source="volcano", dataSource="data", condition1="A",
                                condition2="B", pValueThreshold=0.05, log2fcThreshold=1.0,
                                testType="unpaired", useUncorrected=False)
    stats_tools.ora_plot_png(payload, direction="up", advanced=None, width_cm=20, height_cm=12, dpi=72)
    ax = captured["ax"]
    assert ax.get_xlabel().startswith("GeneRatio")
    xs = sorted(ax.collections[0].get_offsets()[:, 0].tolist())
    assert np.allclose(xs, sorted(t.geneRatio for t in terms))


def test_package_table_and_plot_use_gene_ratio(monkeypatch) -> None:
    db = notebook_functions.load_go_db()
    genes = str(db.iloc[0]["genes"]).split(";")[:12] + str(db.iloc[3]["genes"]).split(";")[:4]
    table = notebook_functions.enrichment_data(genes, top_n=5, min_num=5, max_num=5000,
                                               background_mode="global", adj_p_value_cutoff=1.0)
    assert list(table.columns) == notebook_functions.ENRICHMENT_COLUMNS
    assert not table.empty
    assert (table["query_size"] == table["query_size"].iloc[0]).all()
    assert np.allclose(table["gene_ratio"], table["intersection_size"] / table["query_size"])
    captured = {}
    real_scatter = notebook_functions.plt.Axes.scatter

    def spy(self, *args, **kwargs):
        captured["x"] = np.asarray(kwargs.get("x", args[0] if args else None), dtype=float)
        captured["ax"] = self
        return real_scatter(self, *args, **kwargs)

    monkeypatch.setattr(notebook_functions.plt.Axes, "scatter", spy)
    fig = notebook_functions.enrichment_analysis(genes, top_n=5, min_num=5, max_num=5000,
                                                 background_mode="global", adj_p_value_cutoff=1.0)
    try:
        assert captured["ax"].get_xlabel().startswith("GeneRatio")
        assert np.allclose(sorted(captured["x"]), sorted(table["gene_ratio"]))
    finally:
        notebook_functions.plt.close(fig)


def test_dot_plot_labels_name_each_terms_ontology(monkeypatch) -> None:
    """BP, CC and MF share one plot and one correction, so each label says which (2026-10-02)."""
    from app.schemas.stats import EnrichmentRequest, EnrichmentResultResponse, EnrichmentTerm

    terms = [
        EnrichmentTerm(source=ontology, termId=f"GO:{i:07d}", name=f"term {i}", termSize=100, intersectionSize=3,
                       querySize=30, geneRatio=0.1, hitPercent=3.0, pValue=1e-4, adjPValue=1e-3,
                       intersectingGenes=["G"])
        for i, ontology in enumerate(["BP", "CC", "MF"])
    ]
    result = EnrichmentResultResponse(kind="protein", sourceUsed="data", upTerms=terms, downTerms=[],
                                      backgroundMode="experiment", backgroundGenes=[], backgroundSize=30,
                                      annotatedBackgroundSize=30, organism="Homo sapiens",
                                      databaseSha256="x", testedTermCount=3, termCounts={},
                                      upstreamCorrectionMethod="Benjamini-Hochberg", warnings=[])
    monkeypatch.setattr(stats_tools, "run_enrichment", lambda payload: result)
    captured = {}

    def capture(fig, plt, **kwargs):
        captured["labels"] = [tick.get_text() for tick in fig.axes[0].get_yticklabels()]
        return b"\x89PNG\r\n\x1a\n"

    monkeypatch.setattr(stats_tools, "_to_png_bytes", capture)
    payload = EnrichmentRequest(kind="protein", source="volcano", dataSource="data", condition1="A",
                                condition2="B", pValueThreshold=0.05, log2fcThreshold=1.0,
                                testType="unpaired", useUncorrected=False)
    stats_tools.ora_plot_png(payload, direction="up", advanced=None, width_cm=20, height_cm=12, dpi=72)
    joined = " ".join(label.replace("\n", " ") for label in captured["labels"])
    for i, ontology in enumerate(["BP", "CC", "MF"]):
        assert f"term {i} ({ontology})" in joined


def test_package_plot_labels_name_the_ontology(monkeypatch) -> None:
    import pandas as pd

    table = pd.DataFrame({"source": ["BP", "MF"], "term_name": ["alpha", "beta"], "gene_ratio": [0.1, 0.2],
                          "intersection_size": [3, 4], "adj_p_value": [1e-3, 1e-2]})
    monkeypatch.setattr(notebook_functions, "enrichment_data", lambda *args, **kwargs: table)
    captured = {}
    real_scatter = notebook_functions.plt.Axes.scatter

    def scatter(self, *args, **kwargs):
        captured["y"] = list(kwargs.get("y", []))
        return real_scatter(self, *args, **kwargs)

    monkeypatch.setattr(notebook_functions.plt.Axes, "scatter", scatter)
    notebook_functions.enrichment_analysis(["G1", "G2"])
    assert captured["y"] == ["alpha (BP)", "beta (MF)"]
