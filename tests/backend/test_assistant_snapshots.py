from collections import OrderedDict

import pandas as pd
import pytest

from app.services import assistant_snapshots as snapshots
from app.services.scientific_assistant import _canvas_tile_evidence, _snapshot_evidence


def test_collapsed_canvas_tiles_do_not_compute_or_publish_hidden_results(monkeypatch):
    from app.services import analysis_functions

    def unexpected(*args, **kwargs):
        raise AssertionError("Collapsed tiles must not be recomputed")

    monkeypatch.setattr(analysis_functions, "analysis_volcano_data", unexpected)
    specs = [{"type": "volcano", "collapsed": True}, {"type": "oraList", "collapsed": True}]
    evidence = _canvas_tile_evidence({"tileEvidence": specs}, "compact")
    assert [entry.tool for entry in evidence] == ["canvas tile 1: volcano", "canvas tile 2: oraList"]
    assert all(entry.status == "unavailable" and "collapsed" in entry.text for entry in evidence)


@pytest.fixture
def state(monkeypatch):
    current = {"session": "first", "revision": 1, "time": 0}
    monkeypatch.setattr(snapshots, "_snapshots", OrderedDict())
    monkeypatch.setattr(snapshots, "get_session_id", lambda: current["session"])
    monkeypatch.setattr(snapshots, "runtime_cache_version", lambda: current["revision"])
    monkeypatch.setattr(snapshots, "monotonic", lambda: current["time"])
    return current


@pytest.mark.parametrize("key,value", [("session", "other"), ("revision", 2), ("time", 3601)])
def test_snapshots_are_scoped_and_expire(state, key, value):
    token = snapshots.store_snapshot({"type": "external_ksea", "rows": [{"kinase": "K", "adj_pval": 0}]})
    state[key] = value
    with pytest.raises(ValueError):
        snapshots.read_snapshot(token)


def test_snapshot_copy_limits_and_type_boundary(state):
    token = snapshots.store_snapshot({"type": "external_ksea", "rows": [{"adj_pval": 0}]})
    snapshots.read_snapshot(token)["rows"].clear()
    assert snapshots.read_snapshot(token)["rows"]
    assert _snapshot_evidence(token, "canvas_ora", "compact", "ORA").status == "unavailable"
    assert snapshots.store_snapshot({"text": "x" * 32001}) == ""
    for _ in range(64):
        snapshots.store_snapshot({"type": "external_ksea"})
    assert len(snapshots._snapshots) == 64
    with pytest.raises(ValueError):
        snapshots.read_snapshot(token)


def test_ksea_evidence_matches_rendered_values_and_keeps_groups():
    from app.services.phospho_tools import ksea_uploaded_volcano_html
    st = pd.DataFrame({"Kinase": ["K1"], "Frequency Factor": [2], "Adjusted p-value": [0], "Substrate count": [7]})
    y = pd.DataFrame({"Kinase": ["K2"], "Log2(Frequency Factor)": [-1], "Adjusted p-value": [.2]})
    evidence = {}
    html = ksea_uploaded_volcano_html(st_results=st, tnc_results=y, evidence_out=evidence)
    assert html and evidence["totalRows"] == 2
    first, second = evidence["rows"]
    assert first["log2ff"] == 1 and first["adj_pval"] == 0 and first["substrate_count"] == 7
    assert first["result_group"] == "S/T" and second["result_group"] == "Y"
    assert second["substrate_count"] is None
    assert evidence["counts"] == {"Upregulated": 1, "Not significant": 1}


def test_canvas_reads_each_tile_service_and_isolates_failure(monkeypatch):
    from app.services import analysis_functions
    calls = []
    def table(**settings):
        calls.append(settings)
        return pd.DataFrame({"condition": ["A"], "mean": [0]})
    monkeypatch.setattr(analysis_functions, "analysis_boxplot_table", table)
    specs = [{"type": "proteinBoxplot", "settings": {"kind": "protein", "protein": "P1", "conditions": ["A"], "identifier": "workflow"}},
             {"type": "invented", "settings": {}}]
    evidence = _canvas_tile_evidence({"tileEvidence": specs}, "compact")
    assert calls[0]["protein"] == "P1" and calls[0]["conditions"] == ["A"]
    assert "mean=0" in evidence[0].text and evidence[1].status == "unavailable"


def test_canvas_reads_completed_ora_snapshot_without_running_it(state, monkeypatch):
    from app.services import stats_tools
    monkeypatch.setattr(stats_tools, "run_enrichment_from_list", lambda *args: pytest.fail("Must not rerun ORA"))
    token = snapshots.store_snapshot({"type": "canvas_ora", "querySize": 3, "terms": [{"term": "T", "adjPValue": .01}]})
    evidence = _canvas_tile_evidence({"tileEvidence": [{"type": "oraList", "token": token}]}, "compact")
    assert evidence[0].status == "available" and "adjPValue=0.01" in evidence[0].text


def test_optional_substrate_counts_preserve_unknowns():
    from app.services.phospho_tools import _normalize_ksea_results
    data = pd.DataFrame({"Kinase": ["K1", "K2"], "Frequency Factor": [2, 1],
                         "Adjusted p-value": [.01, .2], "Substrate count": [7, ""],
                         "Number of substrates": [7.0, None]})
    result = _normalize_ksea_results(data)
    assert result["substrate_count"].iloc[0] == 7
    assert pd.isna(result["substrate_count"].iloc[1])


@pytest.mark.parametrize("snapshot_state", ["completed", "unrun", "expired"])
def test_ora_planner_module_reads_visible_tile_not_standalone(state, monkeypatch, snapshot_state):
    from app.schemas.assistant import AssistantPlan, AssistantRequest
    from app.services import scientific_assistant as assistant, stats_tools
    monkeypatch.setattr(assistant, "_module_evidence", lambda *args: pytest.fail("Must not read standalone defaults"))
    monkeypatch.setattr(stats_tools, "run_enrichment_from_list", lambda *args: pytest.fail("Must not rerun ORA"))
    token = snapshots.store_snapshot({"type": "canvas_ora", "querySize": 3,
        "backgroundMode": "experiment", "terms": [{"term": "T", "adjPValue": .01}]})
    if snapshot_state == "expired":
        state["time"] = 3601
    request = AssistantRequest(message="Explain this completed ORA result, including its query, background and adjusted p-values. Do not run ORA again.",
        view={"module": "analysis.canvas", "workflow": "protein", "mode": {"tiles": ["oraList"], "tileEvidence": [
            {"type": "oraList", "token": "" if snapshot_state == "unrun" else token}]}})
    plan = AssistantPlan(task="current_plot", module="stats.ora")
    evidence = assistant.scientific_evidence(request, plan)[-1]
    assert evidence.tool.startswith("canvas tile")
    assert evidence.status == ("available" if snapshot_state == "completed" else "unavailable")
    if snapshot_state == "completed":
        assert "adjPValue=0.01" in evidence.text and "backgroundMode=experiment" in evidence.text
    else:
        assert ("No completed enrichment result" if snapshot_state == "unrun" else "expired") in evidence.text
    assert plan.module == "stats.ora"


@pytest.mark.parametrize("question,task,module,tiles,expected", [
    ("Explain this ORA tile", "current_plot", "stats.ora", ["oraList"], "analysis.canvas"),
    ("Explain the current enrichment result", "current_plot", "stats.ora", ["oraList"], "analysis.canvas"),
    ("Explain the separate ORA page, not this tile", "current_plot", "stats.ora", ["oraList"], "stats.ora"),
    ("Explain standalone ORA", "current_plot", "stats.ora", ["oraList"], "stats.ora"),
    ("Explain CV", "current_plot", "qc.cv", ["oraList"], "qc.cv"),
    ("Explain this ORA method", "help", "stats.ora", ["oraList"], "stats.ora"),
    ("Explain this result", "current_plot", "stats.ora", ["volcano"], "stats.ora"),
    ("Explain this result", "current_plot", "", ["oraList"], ""),
])
def test_visible_ora_routing_preserves_other_modules(question, task, module, tiles, expected):
    from app.schemas.assistant import AssistantPlan, AssistantRequest
    from app.services.scientific_assistant import _evidence_module
    request = AssistantRequest(message=question, view={"module": "analysis.canvas",
        "mode": {"tileEvidence": [{"type": kind} for kind in tiles]}})
    assert _evidence_module(request, AssistantPlan(task=task, module=module)) == expected


def test_snapshot_preview_is_explicitly_partial(state):
    token = snapshots.store_snapshot({"type": "canvas_ora", "totalRows": 11,
                                      "terms": [{"term": "T", "adjPValue": .01}] * 10})
    assert _snapshot_evidence(token, "canvas_ora", "extended", "ORA").status == "partial"


def test_ora_route_to_assistant_retains_completed_result_and_invalidates_revision(state, monkeypatch):
    from app.api import routes_stats
    from app.schemas.stats import ListEnrichmentRequest, ListEnrichmentResultResponse, EnrichmentTerm
    from app.schemas.assistant import AssistantRequest, AssistantPlan
    from app.services.scientific_assistant import scientific_evidence
    term = EnrichmentTerm(source="GO", termId="T", name="Synthetic", termSize=20,
                          intersectionSize=2, querySize=20, geneRatio=0.1, hitPercent=10, pValue=.001, adjPValue=.02,
                          intersectingGenes=["G1", "G2"])
    result = ListEnrichmentResultResponse(genes=["G1", "G2"], terms=[term] * 11,
        backgroundMode="experiment", backgroundSize=100, annotatedBackgroundSize=80,
        databaseSha256="synthetic", testedTermCount=20)
    monkeypatch.setattr(routes_stats, "run_enrichment_from_list", lambda payload: result)
    completed = routes_stats.ora_list_route(ListEnrichmentRequest(genes=["G1", "G2"]))
    monkeypatch.setattr(routes_stats, "run_enrichment_from_list", lambda payload: pytest.fail("Must not rerun"))
    request = AssistantRequest(message="Explain the current plot", view={"module": "analysis.canvas",
        "workflow": "protein", "mode": {"tiles": ["oraList"], "tileEvidence": [
            {"type": "oraList", "token": completed.evidenceToken}]}})
    evidence = scientific_evidence(request, AssistantPlan(task="current_plot"), "extended")[-1]
    assert evidence.status == "partial" and "adjPValue=0.02" in evidence.text
    assert "totalRows=11" in evidence.text
    state["revision"] += 1
    assert scientific_evidence(request, AssistantPlan(task="current_plot"))[-1].status == "unavailable"


@pytest.mark.parametrize("source,raw", [("volcano", False), ("volcano_control", True)])
def test_canvas_volcano_contract_keeps_contrast_and_p_metric(monkeypatch, source, raw):
    from app.services import analysis_functions
    from app.schemas.analysis import AnalysisVolcanoResponse
    calls = []
    def calculate(payload):
        calls.append(payload.model_dump())
        return AnalysisVolcanoResponse(kind="protein", source=source, labelColumn="ProteinNames",
            totalRows=1, upregulatedCount=1, downregulatedCount=0, notSignificantCount=0,
            points=[dict(label="P1", selectionLabel="P1", significance="Upregulated", log2FC=2, negLog10P=3)])
    monkeypatch.setattr(analysis_functions, "analysis_volcano_data", calculate)
    settings = dict(kind="protein", source=source, condition1="A", condition2="B",
                    condition1Control="C", condition2Control="D", useUncorrected=raw, testType="unpaired_welch")
    evidence = _canvas_tile_evidence({"tileEvidence": [
        {"type": "volcano" if source == "volcano" else "volcanoControl", "settings": settings}]}, "extended")[0]
    assert calls[0].items() >= settings.items()
    assert f"p_metric={'raw' if raw else 'BH-adjusted'}" in evidence.text
    assert "negLog10P=3" in evidence.text and "log2FC=2" in evidence.text
    assert "volcano_contrast|" in evidence.text and "B" in evidence.text
    assert f"volcano_selected_p_metric|for_significance={'pval' if raw else 'adj_pval'}" in evidence.text
    assert "volcano_testing|selected_test=unpaired_welch" in evidence.text
    assert "volcano_answer_summary|upregulated=1|downregulated=0" in evidence.text


@pytest.mark.parametrize("source", ["log2", "filtered", "imputed"])
def test_canvas_lineplot_preserves_entity_list_and_condition_order(monkeypatch, source):
    from app.services import analysis_functions
    settings = dict(kind="phospho", identifier="genes", proteins=["G2", "G1"], conditions=["B", "A"], dataSource=source)
    def table(**received):
        assert received == {**{key: value for key, value in settings.items() if key != "dataSource"}, "data_source": source}
        return pd.DataFrame({"protein": ["G2", "G1"], "mean": [0, 2]})
    monkeypatch.setattr(analysis_functions, "analysis_lineplot_table", table)
    evidence = _canvas_tile_evidence({"tileEvidence": [
        {"type": "proteinLineplot", "settings": settings}]}, "extended")[0]
    assert evidence.status == "available" and "protein=G2|mean=0" in evidence.text


@pytest.mark.parametrize("token_kind", ["valid", "missing", "stale"])
@pytest.mark.parametrize("module", ["", "external_activity"])
def test_ksea_browser_boolean_routes_only_to_uploaded_evidence(state, monkeypatch, token_kind, module):
    from app.schemas.assistant import AssistantRequest, AssistantPlan
    from app.services import scientific_assistant as assistant
    monkeypatch.setattr(assistant, "_module_evidence", lambda *args: pytest.fail("Must not substitute export inputs"))
    token = snapshots.store_snapshot({"type": "external_ksea", "rows": [{"kinase": "K1", "log2ff": 2}]})
    if token_kind == "stale":
        state["revision"] += 1
    request = AssistantRequest(message="Explain the current plot", view={"module": "phospho.ksea",
        "workflow": "phosphosite", "mode": {"externalPlotPresent": True,
        "externalEvidenceToken": token if token_kind != "missing" else ""}})
    evidence = assistant.scientific_evidence(request, AssistantPlan(task="current_plot", module=module))
    assert len(evidence) == 1
    assert evidence[0].status == ("available" if token_kind == "valid" else "unavailable")
