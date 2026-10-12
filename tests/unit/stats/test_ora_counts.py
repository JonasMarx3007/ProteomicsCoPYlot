import pytest

from app.schemas.stats import EnrichmentRequest, ListEnrichmentRequest
from app.services import stats_tools


@pytest.fixture
def universe(monkeypatch):
    background = {f'G{i}' for i in range(20)}
    terms = [('BP', 'one', 'one', {'G0'}), ('MF', 'two', 'two', {'G0', 'G1'}),
             ('BP', 'zero', 'zero', {'G19'})]
    monkeypatch.setattr(stats_tools, '_prepare_ora_universe', lambda *_, **__: (background, terms))
    monkeypatch.setattr(stats_tools, '_species_overlap_warning', lambda *_: None)
    monkeypatch.setattr(stats_tools, '_go_database_sha256', lambda organism='human': 'synthetic')
    return background, terms


def test_counts_capture_full_family_before_cutoff_and_top_n(universe):
    background, terms = universe
    full, limited, cutoff, empty = {}, {}, {}, {}
    all_terms = stats_tools._enrichment_terms(['G0'], 10, 1, background, terms, full)
    top = stats_tools._enrichment_terms(['G0'], 1, 1, background, terms, limited)
    assert full == dict(searchSpace=3, overlapTested=2, passingCutoff=2, displayed=2)
    assert limited == {**full, 'displayed': 1}
    assert top[0] == all_terms[0]
    assert stats_tools._enrichment_terms(['G0'], 1, 0.001, background, terms, cutoff) == []
    assert cutoff == dict(searchSpace=3, overlapTested=2, passingCutoff=0, displayed=0)
    assert stats_tools._enrichment_terms([], 10, 1, background, terms, empty) == []
    assert empty == dict(searchSpace=3, overlapTested=0, passingCutoff=0, displayed=0)
    # Cross-ontology BH family is unchanged; zero-overlap terms do not inflate it.
    assert all_terms[0].adjPValue == pytest.approx(0.1)


def test_list_response_reports_counts_even_when_no_terms_are_displayed(universe):
    response = stats_tools.run_enrichment_from_list(ListEnrichmentRequest(
        genes=['G0'], backgroundMode='global', minTermSize=1, adjPValueCutoff=0.001))
    assert response.testedTermCount == 3  # Legacy search-space field is retained.
    assert response.termCounts['query'] == dict(searchSpace=3, overlapTested=2, passingCutoff=0, displayed=0)


@pytest.mark.parametrize('source', ['volcano', 'volcano_control', 'anova'])
def test_direction_and_cluster_counts_are_independent(monkeypatch, universe, source):
    monkeypatch.setattr(stats_tools, '_different_genes', lambda *_: ('filtered', ['G0'], ['G19'], list(universe[0]), []))
    monkeypatch.setattr(stats_tools, '_anova_cluster_genes', lambda *_: ('filtered', [], list(universe[0]), []))
    response = stats_tools.run_enrichment(EnrichmentRequest(
        kind='protein', source=source, condition1='A', condition2='B',
        condition1Control='C', condition2Control='D', selectedCluster=1,
        minTermSize=1, adjPValueCutoff=1, topN=1))
    if source == 'anova':
        assert response.termCounts == {'cluster': dict(searchSpace=3, overlapTested=0, passingCutoff=0, displayed=0)}
    else:
        assert response.termCounts['up'] == dict(searchSpace=3, overlapTested=2, passingCutoff=2, displayed=1)
        assert response.termCounts['down'] == dict(searchSpace=3, overlapTested=1, passingCutoff=1, displayed=1)
