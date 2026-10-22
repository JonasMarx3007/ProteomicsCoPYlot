from types import SimpleNamespace

import pandas as pd
import pytest

from app.schemas.stats import EnrichmentRequest, ListEnrichmentRequest
from app.services import stats_tools as st
from proteomicscopylot import notebook_functions as nb


@pytest.mark.parametrize("kind,column", [("protein", "GeneNames"), ("protein", "Gene_group"), ("phosprot", "Gene_group")])
@pytest.mark.parametrize("source", ["volcano", "volcano_control", "anova"])
def test_all_ora_sources_map_selection_and_background(monkeypatch, kind, column, source):
    frame = pd.DataFrame({column: [" A ; B;A;;", "B;C", "D; E", None],
                          "significance": ["Upregulated", "Downregulated", "Not significant", "Not significant"],
                          "cluster": [1, 2, 2, 2]})
    result = SimpleNamespace(sourceUsed="filtered", labelColumn=column, rows=frame.to_dict("records"), warnings=[])
    monkeypatch.setattr(st, "run_volcano", lambda _: result)
    monkeypatch.setattr(st, "run_volcano_control", lambda _: result)
    monkeypatch.setattr(st, "_anova_dataframe", lambda _: ("filtered", column, frame, []))
    monkeypatch.setattr(st, "_stats_source", lambda *a, **k: ("filtered", frame, pd.DataFrame(), []))
    monkeypatch.setattr(st, "_anova_cluster_dataframe", lambda *a: (frame, None))
    request = EnrichmentRequest(kind=kind, source=source, condition1="A", condition2="B",
                                condition1Control="C", condition2Control="D", selectedCluster=1)
    if source == "anova":
        _, selected, background, _ = st._anova_cluster_genes(request)
    else:
        _, selected, down, background, _ = st._different_genes(request)
        assert down == ["B", "C"]
    assert selected == ["A", "B"]
    assert background == ["A", "B", "C", "D", "E"]


def test_explicit_lists_match_expanded_input_and_python_package(monkeypatch):
    database = pd.DataFrame({"ontology": ["BP"], "term": ["GO:1"],
                             "description": ["test"], "genes": ["A;B"]})
    monkeypatch.setattr(st, "load_go_db", lambda *a: database)
    monkeypatch.setattr(nb, "load_go_db", lambda *a: database)
    common = dict(minTermSize=1, maxTermSize=10, adjPValueCutoff=1.)
    grouped = st.run_enrichment_from_list(ListEnrichmentRequest(
        genes=[" B;A;A", ""], backgroundGenes=[" A;B "], **common))
    expanded = st.run_enrichment_from_list(ListEnrichmentRequest(
        genes=["A", "B"], backgroundGenes=["A", "B"], **common))
    assert grouped.model_dump() == expanded.model_dump()
    for workflow in ("Protein", "Phosphoproteome"):
        a = nb.enrichment_data([" B;A;A"], background=[" A;B "], workflow=workflow,
                               min_num=1, max_num=10, adj_p_value_cutoff=1.)
        b = nb.enrichment_data(["A", "B"], background=["A", "B"], workflow=workflow,
                               min_num=1, max_num=10, adj_p_value_cutoff=1.)
        pd.testing.assert_frame_equal(a, b)
    assert nb._different_gene_tokens(["B;A;A", None, ""]) == ["A", "B"]
