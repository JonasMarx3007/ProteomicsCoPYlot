import json

import pandas as pd
import pytest

from app.schemas.assistant import CanvasFocusRequest
from app.services import canvas_focus


@pytest.fixture
def focus_data(monkeypatch):
    frame = pd.DataFrame({"PTM_Collapse_key": ["P1_S1", "P1_S2", "P2_S1"],
                          "Protein_group": ["P1", "P1", "P2"], "Gene_group": ["G1", "G1", "G2"]})
    meta = pd.DataFrame({"condition": ["A", "B", "C"]})
    calls = []
    def source(kind, data_source="data", **kwargs):
        calls.append(kind)
        if kind != "phospho":
            raise ValueError("Unavailable")
        return "data", frame, meta
    monkeypatch.setattr(canvas_focus, "select_matrix", source)
    return calls


def test_single_site_and_explicit_all_sites_remain_distinct(focus_data):
    single = canvas_focus.resolve_canvas_focus(CanvasFocusRequest(kind="phospho", query="P1_S1", conditions=["B", "A"]), {})
    assert single["features"] == ["P1_S1"] and single["conditions"] == ["B", "A"]
    all_sites = canvas_focus.resolve_canvas_focus(CanvasFocusRequest(kind="phospho", query="P1", allSites=True, conditions=["A", "B"]), {})
    assert all_sites["features"] == ["P1_S1", "P1_S2"]
    with pytest.raises(ValueError, match="No exact match"):
        canvas_focus.resolve_canvas_focus(CanvasFocusRequest(kind="phospho", query="P1", conditions=["A", "B"]), {})


@pytest.mark.parametrize('module,action', [('qc.cv', 'navigate'), ('analysis.canvas', 'focus_canvas')])
def test_canvas_focus_preserves_requested_explanation(focus_data, monkeypatch, module, action):
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    monkeypatch.setattr(assistant, '_execution_profile', lambda *args: ('compact', 2, 600))
    monkeypatch.setattr(assistant, 'assistant_completion', lambda *args, **kwargs: ('scripted', json.dumps({
        'task': 'canvas_focus', 'explainAfterChanges': False,
        'focus': {'kind': 'phospho', 'query': 'P1_S1', 'conditions': ['A', 'B']}})))
    result = assistant.assistant_step(AssistantRequest(message='Show phosphosite P1_S1 on the canvas and explain it',
        view={'module': module, 'destinations': {'analysis.canvas': 'Canvas'}}))
    assert result.actions[0].type == action
    assert result.explainAfterChanges is True


@pytest.mark.parametrize('question', [
    'Explain how to show phosphosite K0 on the canvas',
    'Do not show phosphosite K0 on the canvas and explain it',
    'Explain phosphosite K0 before changing the canvas',
    'Show phosphosite K0 on the canvas and explain why protein P0 is significant',
])
def test_canvas_explanation_shortcut_does_not_consume_other_intent(question):
    from app.services.assistant_routing import canvas_explanation_request
    assert not canvas_explanation_request(question)


def test_protein_request_does_not_substitute_available_sites(focus_data):
    with pytest.raises(ValueError, match="No other level"):
        canvas_focus.resolve_canvas_focus(CanvasFocusRequest(kind="protein", query="P1", conditions=["A", "B"]), {})
    assert focus_data == ["protein"]


def test_existing_other_level_canvas_is_preserved(focus_data):
    with pytest.raises(ValueError, match="another data level"):
        canvas_focus.resolve_canvas_focus(CanvasFocusRequest(kind="phospho", query="P1_S1"), {"kind": "protein", "tiles": ["volcano"]})
    assert not focus_data


def test_linked_comparison_is_used_and_ambiguous_conditions_require_choice(focus_data):
    request = CanvasFocusRequest(kind="phospho", query="P1_S1")
    with pytest.raises(ValueError, match="two distinct"):
        canvas_focus.resolve_canvas_focus(request, {})
    context = {"linkedVolcanoId": "second", "tileEvidence": [
        {"id": "first", "type": "volcano", "settings": {"condition1": "A", "condition2": "B"}},
        {"id": "second", "type": "volcano", "settings": {"condition1": "C", "condition2": "A"}}]}
    assert canvas_focus.resolve_canvas_focus(request, context)["conditions"] == ["C", "A"]


@pytest.mark.parametrize("conditions", [["A"], ["A", "A"], ["A", "missing"]])
def test_invalid_conditions_do_not_change_canvas(focus_data, conditions):
    with pytest.raises(ValueError, match="two distinct"):
        canvas_focus.resolve_canvas_focus(CanvasFocusRequest(kind="phospho", query="P1_S1", conditions=conditions), {})


def test_ambiguous_gene_requires_exact_protein(monkeypatch):
    frame = pd.DataFrame({"ProteinNames": ["P1", "P2"], "GeneNames": ["G", "G"]})
    meta = pd.DataFrame({"condition": ["A", "B"]})
    monkeypatch.setattr(canvas_focus, "select_matrix", lambda *args, **kwargs: ("data", frame, meta))
    with pytest.raises(ValueError, match="multiple features"):
        canvas_focus.resolve_canvas_focus(CanvasFocusRequest(kind="protein", query="G"), {})
    with pytest.raises(ValueError, match="multiple features"):
        canvas_focus.resolve_canvas_focus(CanvasFocusRequest(kind="protein", query="G."), {}, message="Show protein G.")
    assert canvas_focus.resolve_canvas_focus(CanvasFocusRequest(kind="protein", query="P1"), {})["features"] == ["P1"]


def test_ambiguous_feature_choices_are_bounded_and_counted(monkeypatch):
    frame = pd.DataFrame({'ProteinNames': [f'P{i}' for i in range(7)], 'GeneNames': ['G'] * 7})
    meta = pd.DataFrame({'condition': ['A', 'B']})
    monkeypatch.setattr(canvas_focus, 'select_matrix', lambda *args, **kwargs: ('data', frame, meta))
    with pytest.raises(ValueError) as error:
        canvas_focus.resolve_canvas_focus(CanvasFocusRequest(kind='protein', query='G'), {})
    message = str(error.value)
    assert '7 matches' in message and 'first 5' in message
    assert '"P0"' in message and '"P4"' in message and '"P5"' not in message
    assert 'No canvas changes' in message


def test_punctuation_candidate_is_grounded_but_never_automatically_applied(focus_data):
    request = CanvasFocusRequest(kind="phospho", query="P1_S1.", conditions=["A", "B"])
    with pytest.raises(canvas_focus.CanvasIdentifierCandidate) as error:
        canvas_focus.resolve_canvas_focus(request, {}, message="Show phosphosite P1_S1.")
    assert error.value.query == "P1_S1"
    assert request.query == "P1_S1."


@pytest.mark.parametrize("message", ["Show P1_S10.", "Show something else", 'Show "P1_S1."', "Show ‘P1_S1.’"])
def test_candidate_must_be_in_question_and_not_explicitly_quoted(focus_data, message):
    with pytest.raises(ValueError, match="No exact match"):
        canvas_focus.resolve_canvas_focus(CanvasFocusRequest(kind="phospho", query="P1_S1.", conditions=["A", "B"]), {}, message=message)


def test_real_punctuation_identifier_is_preserved(monkeypatch):
    frame = pd.DataFrame({"PTM_Collapse_key": ["K0", "K0."]})
    meta = pd.DataFrame({"condition": ["A", "B"]})
    monkeypatch.setattr(canvas_focus, "select_matrix", lambda *args, **kwargs: ("data", frame, meta))
    assert canvas_focus.resolve_canvas_focus(CanvasFocusRequest(kind="phospho", query="K0."), {}, message="Show K0.")["features"] == ["K0."]


@pytest.mark.parametrize("choice,accepted", [
    ({"query": "P1_S1"}, True), ({"query": ""}, False),
    ({"query": "P2_S1"}, False), ({"query": "P1_S1", "allSites": True}, False),
    ("not-json", False),
])
def test_one_bounded_repair_cannot_change_scope(monkeypatch, focus_data, choice, accepted):
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    calls = []
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    def complete(request, instruction, data, **kwargs):
        calls.append((request.model, kwargs["schema"]))
        if len(calls) == 1:
            return "resolved-model", json.dumps({"task": "canvas_focus", "focus": {
                "kind": "phospho", "query": "P1_S1.", "conditions": ["B", "A"]}})
        assert len(calls) == 2
        assert request.model == "resolved-model"
        assert kwargs["schema"]["properties"]["query"]["enum"] == ["P1_S1", ""]
        return "resolved-model", choice if isinstance(choice, str) else json.dumps(choice)
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    result = assistant.assistant_step(AssistantRequest(message="Show everything on the canvas for phosphosite P1_S1.", view={"module": "analysis.canvas"}))
    assert len(calls) == 2
    if accepted:
        resolved = json.loads(result.actions[0].value)
        assert resolved["features"] == ["P1_S1"] and resolved["conditions"] == ["B", "A"]
        assert resolved["kind"] == "phospho" and not resolved["allSites"]
        assert "Resolved" in result.answer
    else:
        assert not result.actions and result.needsClarification


def test_canvas_guidance_needs_neither_provider_nor_dataset(monkeypatch):
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    def unexpected(*args, **kwargs):
        pytest.fail("Read-only workflow guidance must not call a provider or inspect uploaded data")
    monkeypatch.setattr(assistant, "assistant_completion", unexpected)
    monkeypatch.setattr(assistant, "scientific_evidence", unexpected)
    result = assistant.assistant_step(AssistantRequest(message="Explain how to show all phosphosites on protein P0 in the canvas. Do not change anything.", view={"module": "qc.cv"}))
    assert not result.actions and not result.needsClarification
    assert "explicitly ask" in result.answer and "+ Add Plot" in result.answer
    assert result.evidence[0].tool == "workflow:analysis.canvas"


@pytest.mark.parametrize("message", [
    "How is the fold change calculated in this canvas?",
    "Explain how to use the canvas and then show phosphosite P1_S1.",
    "Show all phosphosites on protein P1 on the canvas",
])
def test_workflow_guidance_does_not_replace_science_or_action_requests(message):
    from app.services.assistant_routing import requests_canvas_guidance
    assert not requests_canvas_guidance(message)


@pytest.mark.parametrize("message,allowed", [
    ("Select phosphosite K79", False),
    ("Open the protein boxplot", False),
    ("Give me everything for protein P1", True),
    ("Could you show all plots for phosphosite K1?", True),
    ("Show phosphosite K1 on the canvas", True),
    ("All plots for protein ABC, B as reference and A as target", True),
    ("Everything for phosphosite K1", True),
    ("Explain all plots for protein ABC", False),
])
def test_focus_task_requires_a_bundle_or_canvas_request(message, allowed):
    from app.services.assistant_routing import planner_tasks
    assert ("canvas_focus" in planner_tasks(message)) == allowed


@pytest.mark.parametrize("invalidated", ["cancel", "revision"])
def test_repair_cannot_apply_after_state_is_invalidated(monkeypatch, focus_data, invalidated):
    import threading
    from app.schemas.assistant import AssistantRequest
    from app.services import scientific_assistant as assistant
    cancelled = threading.Event()
    revision = [1]
    calls = []
    monkeypatch.setattr(assistant, "runtime_cache_version", lambda: revision[0])
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    def complete(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return "model", json.dumps({"task": "canvas_focus", "focus": {"kind": "phospho", "query": "P1_S1.", "conditions": ["A", "B"]}})
        if invalidated == "cancel":
            cancelled.set()
        else:
            revision[0] += 1
        return "model", '{"query":"P1_S1"}'
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    with pytest.raises(ValueError, match="cancelled|analysis changed"):
        assistant.assistant_step(AssistantRequest(message="Show phosphosite P1_S1. on the canvas", view={"module": "analysis.canvas"}), cancelled)
    assert len(calls) == 2
