import json
import threading
import time
from contextvars import ContextVar

import pytest

from app.schemas.assistant import AssistantRequest, Evidence
from app.services import scientific_assistant as assistant


@pytest.fixture
def rig(monkeypatch):
    calls, reads = [], []
    cancelled = threading.Event()
    revision = [1]
    evidence = [Evidence(tool="test", status="available", text="result_answer_summary|count=12")]
    monkeypatch.setattr(assistant, "runtime_cache_version", lambda: revision[0])
    monkeypatch.setattr(assistant, "provider_deadline", ContextVar("test_deadline", default=None))
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    def read(*args):
        reads.append(args)
        return evidence
    monkeypatch.setattr(assistant, "scientific_evidence", read)
    def run(replies, message="Explain this plot", **request_fields):
        pending = iter(replies)
        def complete(request, instruction, data, **kwargs):
            calls.append(json.loads(data))
            reply = next(pending)
            if callable(reply):
                reply = reply()
            if isinstance(reply, Exception):
                raise reply
            return "synthetic", reply
        monkeypatch.setattr(assistant, "assistant_completion", complete)
        view = request_fields.pop("view", {"module": "qc.cv"})
        return assistant.assistant_step(AssistantRequest(message=message, model="synthetic", view=view, **request_fields), cancelled)
    return run, calls, reads, evidence, cancelled, revision


PLAN = '{"task":"current_plot"}'


@pytest.mark.parametrize('name,kind', [('protein boxplot', 'proteinBoxplot'), ('protein lineplot', 'proteinLineplot'),
                                     ('volcano', 'volcano'), ('control volcano', 'volcanoControl'), ('ORA', 'oraList')])
def test_explicit_canvas_addition_bypasses_model(rig, name, kind):
    run, calls, *_ = rig
    result = run([], message=f'Add two {name} tiles to this canvas.', view={'module': 'analysis.canvas', 'workflow': 'phospho'})
    assert result.actions[0].type == 'add_canvas_tiles'
    assert json.loads(result.actions[0].value) == {'type': kind, 'count': 2}
    assert calls == []


def test_canvas_addition_navigation_and_budget(rig):
    run, calls, *_ = rig
    result = run([], message='Please add a protein boxplot tile.', view={'module': 'qc.cv', 'destinations': {'analysis.canvas': 'Canvas'}})
    assert result.actions[0].type == 'navigate'
    for message in ['Add 0 volcano tiles', 'Add 9 volcano tiles', 'Add 8 volcano tiles']:
        with pytest.raises(ValueError):
            run([], message=message, view={'module': 'qc.cv', 'destinations': {'analysis.canvas': 'Canvas'}})
    assert calls == []


@pytest.mark.parametrize('message', ['Do not add one volcano tile', 'Should I add one volcano tile?',
    'Add two volcano tiles and explain them', 'Add one protein boxplot for TP53', 'Add two heatmap tiles', 'Add volcano tiles'])
def test_canvas_addition_does_not_consume_other_intent(message):
    from app.services.assistant_routing import canvas_add_request
    assert canvas_add_request(message) is None


def test_provider_cannot_invent_internal_canvas_addition(rig):
    run, *_ = rig
    with pytest.raises(ValueError, match='application-validated'):
        run([json.dumps({'task': 'ui', 'actions': [{'type': 'add_canvas_tiles', 'value': '{"type":"volcano","count":2}'}]})],
            message='Change the canvas', view={'module': 'analysis.canvas'})


@pytest.mark.parametrize("message,focused,all_sites", [
    ("Give me everything on the canvas for phosphosite K0", True, False),
    ("Show all plots for phosphosite K1 on the canvas", True, False),
    ("Show all phosphosites on protein P0 on the canvas", True, True),
    ("Explain all phosphosites on protein P0 on the canvas", False, True),
    ("Add one protein boxplot tile and rotate its labels", False, False),
])
def test_focus_planner_limits_choices_without_narrowing_advice_or_manual_tiles(monkeypatch, message, focused, all_sites):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    def complete(request, instruction, data, **kwargs):
        schema = kwargs["schema"]
        inputs = json.loads(data)
        if "source" in schema["properties"]:
            assert not focused
            return "scripted", '{"source":"unsupported","query":""}'
        assert (schema["properties"]["task"]["enum"] == ["canvas_focus", "clarify"]) == focused
        assert (schema["$defs"]["CanvasFocusRequest"]["properties"]["allSites"].get("enum") is None) == all_sites
        if focused:
            assert schema["properties"]["actions"]["maxItems"] == 0
            assert "controls" not in inputs["view"] and not inputs["evidenceModules"]
            if not all_sites:
                assert schema["$defs"]["CanvasFocusRequest"]["properties"]["kind"]["enum"] == ["phospho"]
        return "scripted", '{"task":"clarify","clarification":"entity"}'
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    assistant.assistant_step(AssistantRequest(message=message, view={"module": "analysis.canvas"}))


@pytest.mark.parametrize("message,plan", [
    ("Show everything for protein P1", {"task": "canvas_focus", "focus": {"kind": "phospho", "query": "P1"}}),
    ("Show everything for protein P1", {"task": "canvas_focus", "focus": {"kind": "phospho", "query": "P1", "allSites": True}}),
    ("Show everything for protein P1", {"task": "ui", "actions": [{"type": "focus_canvas", "value": "{}"}]}),
    ("Explain protein P1", {"task": "canvas_focus", "focus": {"kind": "protein", "query": "P1"}}),
    ("Select phosphosite K79 in the Protein / Site selection.", {"task": "canvas_focus", "focus": {"kind": "phospho", "query": "K79"}}),
])
def test_focus_cannot_substitute_levels_expand_sites_or_bypass_resolution(rig, message, plan):
    run, *_ = rig
    with pytest.raises(ValueError):
        run([json.dumps(plan)], message=message, view={"module": "analysis.canvas"})


@pytest.mark.parametrize("action,control_type,module,allowed", [
    ("search_options", "select", "singleProtein.boxplot", True),
    ("search_options", "multiple", "singleProtein.boxplot", True),
    ("search_options", "text", "singleProtein.boxplot", False),
    ("activate_control", "button", "analysis.canvas", True),
    ("activate_control", "select", "analysis.canvas", False),
    ("activate_control", "button", "qc.cv", False),
    ("set_control", "button", "analysis.canvas", False),
])
def test_ui_search_and_canvas_action_boundaries(monkeypatch, action, control_type, module, allowed):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    monkeypatch.setattr(assistant, "assistant_completion", lambda *args, **kwargs: ("scripted", json.dumps({
        "task": "ui", "actions": [{"type": action, "target": "known", "value": "P1"}]})))
    request = AssistantRequest(message="Please select a protein or add the requested tile", view={
        "module": module, "controls": [{"id": "known", "label": "Selection", "type": control_type,
        "value": "", "options": ["P1"], "optionCount": 1}]})
    if allowed:
        assert assistant.assistant_step(request).actions[0].type == action
    else:
        with pytest.raises(ValueError):
            assistant.assistant_step(request)
INVALID = '{"paragraphs":["The count is 999."]}'
VALID = '{"observations":["e0r0"]}'


def test_visible_ora_route_is_shared_by_evidence_and_answer_catalogue(rig):
    run, calls, reads, *_ = rig
    result = run(['{"task":"current_plot","module":"stats.ora"}', VALID],
        message="Explain this completed ORA result", view={"module": "analysis.canvas",
        "mode": json.dumps({"tileEvidence": [{"type": "oraList", "token": "synthetic"}]})})
    assert reads[0][1].module == "analysis.canvas"
    assert calls[1]["module"] == "analysis.canvas"
    assert not result.usedEvidenceFallback


@pytest.mark.parametrize("replies,expected", [
    ([PLAN, VALID], False), ([PLAN, INVALID, VALID], False),
    ([PLAN, INVALID, INVALID], True), ([PLAN, '{}', '{}'], True),
])
def test_fallback_status_is_application_owned(rig, replies, expected):
    run, *_ = rig
    assert run(replies).usedEvidenceFallback is expected


def test_incomplete_conversation_is_forwarded_with_fresh_evidence(rig):
    run, calls, reads, *_ = rig
    memory = {"request": "Explain the plot", "module": "qc.cv", "workflow": "protein",
              "selections": [], "completed": ["Opened CV."], "status": "incomplete"}
    result = run([PLAN, VALID], conversationState=memory)
    assert calls[0]["conversationState"] == memory
    assert len(reads) == 1 and not result.usedEvidenceFallback


@pytest.mark.parametrize("actions", [[], [{"type": "advanced_options"}]])
def test_ui_clarification_never_applies_actions_or_reads_results(rig, actions):
    run, calls, reads, *_ = rig
    result = run([json.dumps({"task": "ui", "clarification": "control",
                             "actions": actions, "explainAfterChanges": True})],
                 message="Rotate the labels and explain the plot")
    assert result.needsClarification and not result.actions and not result.explainAfterChanges
    assert result.answer == "Which plot setting should I change, and to what value?"
    assert len(calls) == 1 and not reads


def test_clarification_cannot_include_invented_site_associations(rig):
    run, calls, reads, *_ = rig
    with pytest.raises(ValueError, match="invalid plan"):
        run(['{"task":"clarify","clarification":"P1 has K0 and K1. Which site?"}'], message="Select the site for P1")
    assert len(calls) == 1 and not reads


def test_unresolved_entity_asks_without_explanation_generation(rig):
    run, calls, _, evidence, *_ = rig
    evidence[:] = [Evidence(tool="entity_lookup", status="unavailable", text="No unique exact identifier.")]
    result = run(['{"task":"entity_lookup","query":"P1"}', '{"source":"entity_lookup","query":"P1"}'], message="Which site belongs to P1?")
    assert result.needsClarification and "exact" in result.answer
    assert len(calls) == 2 and "selected" not in result.answer


def test_unrun_canvas_ora_does_not_invent_missing_dataset_prerequisites(rig):
    run, calls, _, evidence, *_ = rig
    evidence[:] = [Evidence(tool="canvas", status="available", text="canvas|tiles=1"),
                   Evidence(tool="canvas tile 1: oraList", status="unavailable", text="No completed enrichment result is available for this tile.")]
    result = run([PLAN])
    assert "no completed enrichment result" in result.answer
    assert "protein" not in result.answer and len(calls) == 1


def test_repeated_completed_control_is_not_executed_again(monkeypatch):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    observed = []
    def complete(request, instruction, data, **kwargs):
        observed.append(json.loads(data))
        return "scripted", '{"task":"ui","actions":[{"type":"set_control","target":"site","value":"K79"}]}'
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    result = assistant.assistant_step(AssistantRequest(message="Select site K79", view={"module":"singleProtein.boxplot", "workflow":"protein", "mode":'{"kind":"phospho"}',
        "controls":[{"id":"site","label":"Protein / Site","type":"select","value":"K79","options":["K79"],"optionCount":1}]}))
    assert not result.actions
    assert observed[0]["view"]["workflow"] == "phosphosite"
    assert observed[0]["view"]["advancedOptions"] is False


def test_pure_navigation_does_not_authorize_unrequested_explanation():
    from app.services.assistant_routing import planner_tasks
    assert planner_tasks("Open the protein boxplot.") == ["ui", "clarify"]
    assert "current_plot" in planner_tasks("Open the protein boxplot and explain it.")
    assert planner_tasks("Make the plot more significant.") == ["clarify"]


@pytest.mark.parametrize("question,expected", [("Rotate x labels to 45 degrees", True),
    ("Use advanced options to rename sample A1", True), ("How do I rotate labels?", False),
    ("Don't change the font", False), ("Make this more significant", False)])
def test_styling_discovery_requires_an_explicit_view_request(question, expected):
    from app.services.assistant_routing import requests_advanced_styling
    assert requests_advanced_styling(question) is expected


def test_explicit_styling_reveals_controls_without_model_guessing(monkeypatch):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    monkeypatch.setattr(assistant, "assistant_completion", lambda *args, **kwargs: pytest.fail("Unnecessary planner call"))
    request = AssistantRequest(message="Rotate x labels to 45 degrees", model="synthetic", view={
        "module":"singleProtein.boxplot", "controls":[{"id":"dpi", "label":"DPI", "type":"number", "value":"300"}]})
    result = assistant.assistant_step(request)
    assert [action.type for action in result.actions] == ["advanced_options"]


@pytest.mark.parametrize("empty", ['{}', '{"paragraphs":["  "]}'])
def test_empty_answer_uses_bounded_repair(rig, empty):
    run, calls, reads, *_ = rig
    result = run([PLAN, empty, VALID])
    assert "count: 12" in result.answer
    assert len(calls) == 3 and len(reads) == 1


def test_repeated_empty_answer_returns_honest_evidence_fallback(rig):
    run, calls, reads, *_ = rig
    result = run([PLAN, '{}', '{}'])
    assert "couldn't produce a validated explanation" in result.answer
    assert "count: 12" in result.answer
    assert len(calls) == 3 and len(reads) == 1


def test_mixed_ui_plan_retains_explanation_intent_without_reading_results(rig):
    run, calls, reads, *_ = rig
    result = run(['{"task":"ui","explainAfterChanges":true,"actions":[{"type":"advanced_options"}]}'],
                 message="Enable advanced options and explain this plot")
    assert result.explainAfterChanges and result.actions
    assert len(calls) == 1 and not reads


def test_after_changes_answer_uses_fresh_evidence_without_controls(rig):
    run, calls, reads, *_ = rig
    result = run([PLAN, '{"source":"current_result","query":""}', VALID], message="Rotate the labels and explain this plot", answerOnly=True,
                 receipts=["Rotated labels."])
    assert "count: 12" in result.answer
    assert calls[0]["answerOnly"] is True
    assert calls[1]["answerOnly"] is True
    assert calls[0]["completed"] == ["Rotated labels."]
    assert "controls" not in calls[0]["view"] and "destinations" not in calls[0]["view"]
    assert len(reads) == 1


def test_after_changes_answer_cannot_return_to_ui(rig):
    run, _, reads, *_ = rig
    with pytest.raises(ValueError, match="does not authorize"):
        run(['{"task":"ui","actions":[{"type":"advanced_options"}]}'],
            message="Rotate the labels and explain this plot", answerOnly=True)
    assert not reads


@pytest.mark.parametrize("question,allows_ui", [
    ("Explain this plot and rotate the labels", True),
    ("Explain this plot; then open the CV tab", True),
    ("Explain how to rotate the labels", False),
    ("How do I select a protein?", False),
    ("Explain this plot and don't change anything", False),
])
def test_mixed_request_narrowing_preserves_advice_boundary(question, allows_ui):
    from app.services.assistant_routing import planner_tasks
    assert ("ui" in planner_tasks(question)) is allows_ui


def test_one_repair_reuses_evidence_and_does_not_replay_bad_output(rig):
    run, calls, reads, _, _, _ = rig
    result = run([PLAN, INVALID, VALID])
    assert "count: 12" in result.answer
    assert len(calls) == 3 and len(reads) == 1
    assert calls[1]["catalogue"] == calls[2]["catalogue"]
    assert "schema" in calls[2]["repair"]["problem"]
    assert "999" not in json.dumps(calls[2])
    assert not result.actions


def test_failed_repair_returns_only_application_evidence(rig):
    run, calls, reads, _, _, _ = rig
    result = run([PLAN, INVALID, '{"paragraphs":["{{invented}}"]}'])
    assert len(calls) == 3 and len(reads) == 1
    assert "couldn't produce a validated explanation" in result.answer
    assert "count: 12" in result.answer
    assert "999" not in result.answer and "invented" not in result.answer
    assert not result.actions


def test_schema_feedback_does_not_echo_model_content(rig):
    run, calls, _, _, _, _ = rig
    run([PLAN, '{"secret_field":"synthetic-private-value"}', VALID])
    assert "synthetic-private-value" not in json.dumps(calls[2])
    assert "secret_field" not in json.dumps(calls[2])


@pytest.mark.parametrize("stage", ["first", "repair"])
def test_transport_errors_are_not_retried_or_hidden(rig, stage):
    run, calls, _, _, _, _ = rig
    replies = [PLAN] + ([INVALID] if stage == "repair" else []) + [ValueError("Provider unavailable")]
    with pytest.raises(ValueError, match="Provider unavailable"):
        run(replies)
    assert len(calls) == len(replies)


@pytest.mark.parametrize("reason", ["cancel", "revision", "deadline"])
@pytest.mark.parametrize("stage", ["before_repair", "before_fallback"])
def test_recovery_never_ignores_invalidated_state(rig, reason, stage):
    run, calls, _, _, cancelled, revision = rig
    def invalidate():
        if reason == "cancel":
            cancelled.set()
        elif reason == "revision":
            revision[0] += 1
        else:
            assistant.provider_deadline.set(time.monotonic() - 1)
        return INVALID
    replies = [PLAN] + ([INVALID] if stage == "before_fallback" else []) + [invalidate]
    with pytest.raises(ValueError, match="cancelled|analysis changed|time limit"):
        run(replies)
    assert len(calls) == len(replies)


@pytest.mark.parametrize("plan", ['not-json', '{"task":"ui","actions":[{"type":"delete","target":"dataset"}]}'])
def test_plans_are_not_repaired(rig, plan):
    run, calls, reads, _, _, _ = rig
    with pytest.raises(ValueError):
        run([plan], message="Change the plot")
    assert len(calls) == 1 and not reads


def test_ui_actions_are_returned_once_without_answer_repair(rig):
    run, calls, reads, _, _, _ = rig
    result = run(['{"task":"ui","actions":[{"type":"advanced_options","value":true}]}'], message="Enable advanced options")
    assert len(calls) == 1 and not reads
    assert len(result.actions) == 1


def test_fallback_does_not_present_unavailable_measurements(rig):
    run, _, _, evidence, _, _ = rig
    evidence[0].status = "unavailable"
    result = run([PLAN, INVALID, INVALID])
    assert "No calculated result" in result.answer
    assert "count: 12" not in result.answer


def test_fallback_preserves_partial_and_default_source_qualifications(rig):
    run, _, _, evidence, _, _ = rig
    evidence[0].status = "partial"
    evidence[0].text += "\nRequested module uses default settings, not current UI selections."
    result = run([PLAN, INVALID, INVALID])
    assert "not an exhaustive" in result.answer and "default settings" in result.answer


def test_repair_uses_fallback_if_feedback_would_exceed_input_budget(rig, monkeypatch):
    run, calls, _, _, _, _ = rig
    def fail_at_budget():
        monkeypatch.setattr(assistant, "ASSISTANT_INPUT_MAX_CHARS", len(json.dumps(calls[-1], separators=(",", ":"))))
        return INVALID
    result = run([PLAN, fail_at_budget])
    assert result.usedEvidenceFallback
    assert len(calls) == 2
    assert "count: 12" in result.answer


def test_answer_and_repair_pin_the_model_resolved_by_planning(monkeypatch):
    models = []
    replies = iter([PLAN, INVALID, VALID])
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    monkeypatch.setattr(assistant, "scientific_evidence", lambda *args: [Evidence(tool="test", status="available", text="result|count=12")])
    def complete(request, *args, **kwargs):
        models.append((request.provider, request.model))
        return "resolved-model", next(replies)
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    result = assistant.assistant_step(AssistantRequest(message="Explain this plot", provider="ollama", view={"module": "qc.cv"}))
    assert models == [("ollama", None), ("ollama", "resolved-model"), ("ollama", "resolved-model")]
    assert result.model == "resolved-model" and "count: 12" in result.answer


@pytest.mark.parametrize("provider", ["ollama", "openai", "anthropic", "gemini"])
def test_relevance_corrects_wrong_diagnostic_before_reading(rig, provider):
    run, calls, reads, *_ = rig
    result = run(['{"task":"qc_review"}', '{"source":"result:qc.cv","query":""}', VALID],
                 message="Which condition has the greater CV?", provider=provider)
    assert reads[0][1].task == "current_plot" and reads[0][1].module == "qc.cv"
    assert len(reads) == 1 and not result.actions
    assert "source" not in calls[0] and calls[1]["proposed"]["task"] == "qc_review"
    assert len(json.dumps(calls[1])) < assistant.ASSISTANT_INPUT_MAX_CHARS


def test_visible_result_cannot_be_replaced_by_other_module(rig):
    run, calls, reads, *_ = rig
    run(['{"task":"current_plot","module":"phospho.phosphositePlot"}', VALID],
        message="Explain this plot", view={"module": "singleProtein.boxplot"})
    assert reads[0][1].module == "singleProtein.boxplot"
    assert len(calls) == 2


def test_explicit_other_result_uses_relevance_selection(rig):
    run, _, reads, *_ = rig
    run([PLAN, '{"source":"result:qc.cv","query":""}', VALID],
        message="Explain the other CV plot", view={"module": "singleProtein.boxplot"})
    assert reads[0][1].module == "qc.cv"


def test_specific_question_about_visible_plot_still_checks_relevance(rig):
    run, calls, reads, *_ = rig
    run([PLAN, '{"source":"external_activity","query":""}', VALID],
        message="Does this plot establish AKT1 kinase activity?", view={"module": "singleProtein.boxplot"})
    assert reads[0][1].module == "external_activity" and len(calls) == 3


@pytest.mark.parametrize("selection", ["not json", "[]", '{"source":[],"query":""}',
    '{"source":"ui","query":""}', '{"source":"result:invented","query":""}',
    '{"source":"current_result","query":"","actions":[]}',
    '{"source":"current_result","query":"P1"}', '{"source":"entity_lookup","query":"invented"}',
    '{"source":"entity_lookup","query":""}', '{"source":"unsupported","query":""}'])
def test_invalid_relevance_selection_never_reads_or_changes_data(rig, selection):
    run, calls, reads, *_ = rig
    result = run([PLAN, selection], message="What is measured for P1?")
    assert result.needsClarification and not result.actions and not reads and len(calls) == 2


def test_valid_but_irrelevant_method_can_be_replaced_without_data_access(monkeypatch):
    replies = iter(['{"task":"help","module":"phospho.phosprotRegulation"}',
                    '{"source":"method:completeness.missingPlot","query":""}'])
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    monkeypatch.setattr(assistant, "assistant_completion", lambda *args, **kwargs: ("synthetic", next(replies)))
    monkeypatch.setattr(assistant, "_module_evidence", lambda *args: pytest.fail("Method read uploaded data"))
    result = assistant.assistant_step(AssistantRequest(message="Does non-detection establish absence?", view={"module": "qc.cv"}))
    assert "does not establish biological absence" in result.answer and not result.actions


def test_activity_question_recovers_from_unnecessary_entity_clarification(monkeypatch):
    replies = iter(['{"task":"clarify","clarification":"entity"}',
                    '{"source":"external_activity","query":""}'])
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    monkeypatch.setattr(assistant, "assistant_completion", lambda *args, **kwargs: ("synthetic", next(replies)))
    monkeypatch.setattr(assistant, "_module_evidence", lambda *args: pytest.fail("Activity must not use abundance/export"))
    result = assistant.assistant_step(AssistantRequest(message="Is AKT1 kinase activity increased?", view={"module": "qc.cv"}))
    assert "inputs, not kinase-activity results" in result.answer
    assert not result.actions and result.evidence[0].status == "unavailable"


def test_activity_uses_only_the_uploaded_snapshot(monkeypatch):
    from app.schemas.assistant import AssistantPlan
    seen = []
    monkeypatch.setattr(assistant, "_snapshot_evidence", lambda *args: seen.append(args) or Evidence(tool="uploaded", status="available", text="result"))
    request = AssistantRequest(message="Explain kinase activity", view={"module": "phospho.ksea",
        "mode": json.dumps({"externalPlotPresent": True, "externalEvidenceToken": "snapshot"})})
    result = assistant.scientific_evidence(request, AssistantPlan(task="current_plot", module="external_activity"))
    assert result[0].tool == "uploaded" and seen[0][:2] == ("snapshot", "external_ksea")


def test_action_schema_binds_targets_values_and_standalone_transitions():
    from app.services.assistant_routing import ui_actions_schema
    schema = ui_actions_schema({"module": "analysis.canvas", "advancedOptions": False,
        "destinations": {"analysis.canvas": "Canvas", "qc.cv": "CV"}, "controls": [
            {"id": "tile", "type": "select", "options": ["proteinBoxplot", "volcano"], "optionCount": 2},
            {"id": "site", "type": "select", "options": ["K0"], "optionCount": 80},
            {"id": "add", "type": "button"}, {"id": "top", "type": "checkbox"},
            {"id": "left", "type": "checkbox"}, {"id": "color", "type": "color"},
        ]}, 4)
    empty, setters, transitions = schema["anyOf"]
    assert empty == {"maxItems": 0}
    assert setters["maxItems"] == 4 and transitions["maxItems"] == 1
    by_target = {target: item["properties"] for item in setters["items"]["anyOf"]
                 for target in item["properties"]["target"]["enum"]}
    assert "add" not in by_target
    assert by_target["tile"]["value"]["enum"] == ["proteinBoxplot", "volcano"]
    assert "enum" not in by_target["site"]["value"]  # Exact identifiers outside the truncated window remain allowed.
    assert by_target["top"]["value"] == {"type": "boolean"}
    assert by_target["top"] is by_target["left"]
    targets = {item["properties"]["type"]["enum"][0]: item["properties"]["target"]["enum"]
               for item in transitions["items"]["anyOf"]}
    assert targets == {"navigate": ["qc.cv"], "advanced_options": [""], "search_options": ["tile", "site"], "activate_control": ["add"]}


@pytest.mark.parametrize("kind,value,extra", [
    ("checkbox", "true", {}), ("text", True, {}), ("multiple", "A", {}),
    ("number", "nan", {}), ("number", "inf", {}), ("number", "46", {"max": 45}),
    ("number", "-1", {"min": 0}), ("color", "red", {}),
    ("select", "invented", {"options": ["A"], "optionCount": 1}),
    ("multiple", ["B"], {"options": ["A"], "optionCount": 1}),
])
def test_server_rejects_invalid_control_values_before_ui(rig, kind, value, extra):
    run, _, reads, *_ = rig
    with pytest.raises(ValueError, match="Invalid value"):
        run([json.dumps({"task": "ui", "actions": [{"type": "set_control", "target": "known", "value": value}]})],
            message="Set the requested plot control", view={"module": "qc.cv", "advancedOptions": True,
            "controls": [{"id": "known", "label": "Known", "type": kind, "value": "", **extra}]})
    assert not reads


@pytest.mark.parametrize("kind,current,value,extra", [
    ("number", "45", "45.0", {}),
    ("multiple", ["A", "B"], ["B", "A"], {"options": ["A", "B"]}),
])
def test_equivalent_control_values_are_verified_complete(rig, kind, current, value, extra):
    run, calls, reads, *_ = rig
    result = run([json.dumps({"task": "ui", "actions": [{"type": "set_control", "target": "known", "value": value}]})],
        message="Set the requested plot control", view={"module": "qc.cv", "advancedOptions": True,
        "controls": [{"id": "known", "label": "Known", "type": kind, "value": current, **extra}]})
    assert not result.actions and not reads and len(calls) == 1
    assert "already in place" in result.answer


def test_conflicting_setters_in_one_batch_are_rejected(rig, monkeypatch):
    run, *_ = rig
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("extended", 4, 2000))
    actions = [{"type": "set_control", "target": "known", "value": value} for value in ["10", "20"]]
    with pytest.raises(ValueError, match="only once per batch"):
        run([json.dumps({"task": "ui", "actions": actions})], message="Set plot width",
            view={"module": "qc.cv", "advancedOptions": True, "controls": [
                {"id": "known", "label": "Width", "type": "number", "value": "0"}]})


@pytest.mark.parametrize("action", [{"type": "navigate", "target": "qc.cv"}, {"type": "advanced_options", "value": True}])
def test_already_reached_view_transitions_finish_without_another_action(rig, action):
    run, calls, reads, *_ = rig
    result = run([json.dumps({"task": "ui", "explainAfterChanges": True, "actions": [action]})],
        message="Open CV and explain it", view={"module": "qc.cv", "advancedOptions": True})
    assert not result.actions and result.explainAfterChanges and len(calls) == 1 and not reads


def test_generation_schema_obeys_remaining_action_budget(monkeypatch):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("extended", 4, 2000))
    def complete(*args, schema):
        assert schema["properties"]["actions"]["maxItems"] == 1
        return "synthetic", '{"task":"ui","actions":[]}'
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    assistant.assistant_step(AssistantRequest(message="Open CV", view={"module": "qc.cv"}, receipts=["Done"] * 7))


def test_large_selection_is_not_limited_to_the_advertised_option_window(rig):
    run, *_ = rig
    selected = [f"K{i}" for i in range(90)]
    result = run([json.dumps({"task": "ui", "actions": [{"type": "set_control", "target": "sites", "value": selected}]})],
        message="Select these sites", view={"module": "qc.cv", "advancedOptions": True, "controls": [
            {"id": "sites", "label": "Sites", "type": "multiple", "value": [], "options": selected[:40], "optionCount": 100}]})
    assert result.actions[0].value == selected
