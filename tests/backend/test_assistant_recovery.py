import json
import threading
import time

import pytest
from app.schemas.assistant import AssistantRequest, Evidence
from app.services import chat_tools, scientific_assistant as assistant
from assistant_support import PLAN, VALID, _control, _labels_view, _volcano_view


INVALID = '{"paragraphs":["The count is 999."]}'


def test_an_explanation_that_would_overflow_the_window_uses_the_application_summary(assistant_rig, monkeypatch):
    replies = iter(['{"task":"current_plot"}', '{"source":"current_result","query":""}'])

    def complete(request, instruction, data, **kwargs):
        if instruction.startswith("Select a concise"):
            raise chat_tools.AssistantContextExhausted("full")
        return "synthetic", next(replies)
    request = AssistantRequest(message="Explain this plot", model="synthetic", view={"module": "qc.cv"})
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    result = assistant.assistant_step(request, threading.Event())
    assert result.usedEvidenceFallback and result.answer


def test_a_flag_inside_the_action_list_no_longer_invalidates_the_plan(assistant_rig):
    run = assistant_rig.run
    plan = {"task": "ui", "actions": [{"type": "set_control", "target": "test", "value": "unpaired_welch"},
                                      {"explainAfterChanges": True}]}
    result = run([json.dumps(plan)], message="Change the test to Welch and explain the result.", view=_volcano_view())
    assert [(a.type, a.value) for a in result.actions] == [("set_control", "unpaired_welch")]
    assert result.explainAfterChanges


@pytest.mark.parametrize("item", [{"explainAfterChanges": "yes"}, {"explainAfterChanges": True, "type": "navigate"}, {}, {"value": 1}])
def test_only_an_exact_flag_object_is_lifted(assistant_rig, item):
    run = assistant_rig.run
    plan = {"task": "ui", "actions": [{"type": "set_control", "target": "test", "value": "unpaired_welch"}, item]}
    with pytest.raises(ValueError, match="invalid plan"):
        run([json.dumps(plan)], message="Change the test to Welch.", view=_volcano_view())


def test_an_explanation_step_that_repeats_the_applied_setter_still_explains(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.plans
    view = _volcano_view()
    view["controls"][0]["value"] = "unpaired_welch"
    plan = {"task": "current_plot", "module": "stats.volcano",
            "actions": [{"type": "set_control", "target": "test", "value": "unpaired_welch"}]}
    result = run([json.dumps(plan), '{"source":"current_result","query":""}', '{"observations":["e0r0"]}'],
                 message="Change the test to Welch and explain the result.", view=view, answerOnly=True,
                 receipts=["Set Test type to unpaired_welch."])
    assert result.answer and not result.actions and reads


def test_a_real_change_in_an_explanation_step_is_still_refused(assistant_rig):
    run = assistant_rig.run
    plan = {"task": "current_plot", "actions": [{"type": "set_control", "target": "test", "value": "paired"}]}
    with pytest.raises(ValueError, match="cannot change the interface"):
        run([json.dumps(plan)], message="Explain this plot", view=_volcano_view(), answerOnly=True)


def test_a_rejected_proposal_after_completed_changes_ends_cleanly(assistant_rig):
    run = assistant_rig.run
    plan = {"task": "ui", "styles": [{"element":"condition:A", "property":"color", "value":"not-a-colour"}]}
    result = run([json.dumps(plan)], message="Make condition A red and rotate the labels 45 degrees.",
                 view=_labels_view(), receipts=["Set X axis / X tick label rotation to \"45\"."])
    assert result.stoppedEarly and not result.actions and not result.needsClarification
    assert "valid colour" in result.answer
    assert "Nothing was changed" not in result.answer and "Nothing else was changed" in result.answer


def test_before_any_change_a_rejected_proposal_is_still_an_error(assistant_rig, monkeypatch):
    monkeypatch.setattr(assistant, "_simple_style_plan", lambda request: None)
    run = assistant_rig.run
    plan = {"task": "ui", "styles": [{"element":"condition:A", "property":"color", "value":"not-a-colour"}]}
    with pytest.raises(ValueError, match="valid colour"):
        run([json.dumps(plan)], message="Make condition A red.", view=_labels_view())


def test_a_clean_stop_keeps_a_requested_explanation(assistant_rig):
    run = assistant_rig.run
    result = run(['not json'], message="Rotate the labels 45 degrees and explain the plot.", view=_labels_view(),
                 receipts=["Set X axis / X tick label rotation to \"45\"."])
    assert result.stoppedEarly and result.explainAfterChanges


def test_search_only_progress_does_not_claim_completed_changes(assistant_rig):
    run = assistant_rig.run
    with pytest.raises(ValueError, match="invalid plan"):
        run(['not json'], message="Find phosphosite K79.", view=_labels_view(),
            receipts=['Searched selection options for "K79"; no view changed.'])


@pytest.mark.parametrize("replies,expected", [
    ([PLAN, VALID], False), ([PLAN, INVALID, VALID], False),
    ([PLAN, INVALID, INVALID], True), ([PLAN, '{}', '{}'], True),
])
def test_fallback_status_is_application_owned(assistant_rig, replies, expected):
    run = assistant_rig.run
    assert run(replies).usedEvidenceFallback is expected


@pytest.mark.parametrize("empty", ['{}', '{"paragraphs":["  "]}'])
def test_empty_answer_uses_bounded_repair(assistant_rig, empty):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run([PLAN, empty, VALID])
    assert "count: 12" in result.answer
    assert len(calls) == 3 and len(reads) == 1


def test_repeated_empty_answer_returns_honest_evidence_fallback(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run([PLAN, '{}', '{}'])
    assert "couldn't produce a validated explanation" in result.answer
    assert "count: 12" in result.answer
    assert len(calls) == 3 and len(reads) == 1


def test_mixed_ui_plan_retains_explanation_intent_without_reading_results(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run(['{"task":"ui","explainAfterChanges":true,"styles":[{"element":"x ticks","property":"rotation","operation":"set","value":"45"}]}'],
                 message="Rotate the x tick labels to 45 degrees and explain this plot",
                 view={"module": "qc.cv", "controls": [_control("rot", "X tick label rotation", value="0")]})
    assert result.explainAfterChanges and result.actions
    assert len(calls) == 1 and not reads


def test_after_changes_answer_uses_fresh_evidence_without_controls(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run([PLAN, '{"source":"current_result","query":""}', VALID], message="Rotate the labels and explain this plot", answerOnly=True,
                 receipts=["Rotated labels."])
    assert "count: 12" in result.answer
    assert calls[0]["answerOnly"] is True
    assert calls[1]["answerOnly"] is True
    assert calls[0]["completed"] == ["Rotated labels."]
    assert "controls" not in calls[0]["view"] and "destinations" not in calls[0]["view"]
    assert len(reads) == 1


def test_after_changes_answer_cannot_return_to_ui(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.reads
    with pytest.raises(ValueError, match="does not authorize"):
        run(['{"task":"ui","actions":[{"type":"navigate","target":"qc.cv"}]}'],
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


def test_one_repair_reuses_evidence_and_does_not_replay_bad_output(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run([PLAN, INVALID, VALID])
    assert "count: 12" in result.answer
    assert len(calls) == 3 and len(reads) == 1
    assert calls[1]["catalogue"] == calls[2]["catalogue"]
    assert "schema" in calls[2]["repair"]["problem"]
    assert "999" not in json.dumps(calls[2])
    assert not result.actions


def test_failed_repair_returns_only_application_evidence(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run([PLAN, INVALID, '{"paragraphs":["{{invented}}"]}'])
    assert len(calls) == 3 and len(reads) == 1
    assert "couldn't produce a validated explanation" in result.answer
    assert "count: 12" in result.answer
    assert "999" not in result.answer and "invented" not in result.answer
    assert not result.actions


def test_schema_feedback_does_not_echo_model_content(assistant_rig):
    run, calls = assistant_rig.run, assistant_rig.calls
    run([PLAN, '{"secret_field":"synthetic-private-value"}', VALID])
    assert "synthetic-private-value" not in json.dumps(calls[2])
    assert "secret_field" not in json.dumps(calls[2])


@pytest.mark.parametrize("stage", ["first", "repair"])
def test_transport_errors_are_not_retried_or_hidden(assistant_rig, stage):
    run, calls = assistant_rig.run, assistant_rig.calls
    replies = [PLAN] + ([INVALID] if stage == "repair" else []) + [ValueError("Provider unavailable")]
    with pytest.raises(ValueError, match="Provider unavailable"):
        run(replies)
    assert len(calls) == len(replies)


@pytest.mark.parametrize("reason", ["cancel", "revision", "deadline"])
@pytest.mark.parametrize("stage", ["before_repair", "before_fallback"])
def test_recovery_never_ignores_invalidated_state(assistant_rig, reason, stage):
    run, calls, cancelled, revision = assistant_rig.run, assistant_rig.calls, assistant_rig.cancelled, assistant_rig.revision
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
def test_plans_are_not_repaired(assistant_rig, plan):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    with pytest.raises(ValueError):
        run([plan], message="Change the plot")
    assert len(calls) == 1 and not reads


def test_ui_actions_are_returned_once_without_answer_repair(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run(['{"task":"ui","styles":[{"element":"x ticks","property":"rotation","operation":"set","value":"45"}]}'],
                 message="Rotate the x tick labels to 45 degrees",
                 view={"module": "qc.cv", "controls": [_control("rot", "X tick label rotation", value="0")]})
    assert len(calls) == 1 and not reads
    assert len(result.actions) == 1


def test_fallback_does_not_present_unavailable_measurements(assistant_rig):
    run, evidence = assistant_rig.run, assistant_rig.evidence
    evidence[0].status = "unavailable"
    result = run([PLAN, INVALID, INVALID])
    assert "No calculated result" in result.answer
    assert "count: 12" not in result.answer


def test_fallback_preserves_partial_and_default_source_qualifications(assistant_rig):
    run, evidence = assistant_rig.run, assistant_rig.evidence
    evidence[0].status = "partial"
    evidence[0].text += "\nRequested module uses default settings, not current UI selections."
    result = run([PLAN, INVALID, INVALID])
    assert "not every row of it" in result.answer and "default settings" in result.answer


def test_repair_uses_fallback_if_feedback_would_exceed_input_budget(assistant_rig, monkeypatch):
    run, calls = assistant_rig.run, assistant_rig.calls
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
