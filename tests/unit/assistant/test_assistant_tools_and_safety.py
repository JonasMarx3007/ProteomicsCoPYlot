"""Native tools, the review step, speed and budgets -- inside the same fence.

The fence: no model, through any interface, may change how data are filtered,
normalized, imputed or transformed, or the localization cutoff; every plan a
tool conversation produces runs through the same validation as a JSON plan.
"""
import json
from types import SimpleNamespace

import pytest

from app.schemas.assistant import AssistantRequest, UiAction
from app.services import assistant_profiles, assistant_prose, assistant_safety, assistant_tools
from app.services import scientific_assistant as assistant

from test_assistant_levels import _coverage_view, _targets

IMAGE = "data:image/png;base64,iVBORw0KGgo="


def _with_pipeline(view):
    view = json.loads(json.dumps(view))
    view["controls"] += [
        {"id": "loc", "label": "Localization probability cutoff", "type": "number", "value": "0", "permission": "confirm"},
        {"id": "norm", "label": "Normalization", "type": "select", "value": "none", "options": ["none", "median"],
         "permission": "confirm"},
        {"id": "src", "label": "Data Source", "type": "select", "value": "filtered", "options": ["filtered", "imputed"],
         "permission": "confirm"},
    ]
    return view


@pytest.fixture
def advanced(assistant_rig):
    assistant_rig.profile["value"] = ("extended", 6, 2000)
    return assistant_rig


# --- the fence ------------------------------------------------------------

def test_pipeline_settings_never_reach_a_model(assistant_rig):
    reply = json.dumps({"task": "clarify", "clarification": "pipeline"})
    result = assistant_rig.run([reply], message="set the normalization to median", view=_with_pipeline(_coverage_view()))
    sent = json.dumps(assistant_rig.calls[0])
    assert "Normalization" not in sent and "Localization probability" not in sent
    assert "Data Source" in sent  # choosing which processed matrix to show is a view choice
    assert result.needsClarification and "never changes how data are filtered" in result.answer


@pytest.mark.parametrize("label", ["Localization probability cutoff", "Normalization", "Imputation method",
                                   "Filter *_M1", "Minimum valid values", "log2 transformation"])
def test_any_action_on_a_pipeline_setting_is_refused(label):
    request = AssistantRequest(message="x", view={"module": "qc.cv", "controls": [
        {"id": "p", "label": label, "type": "text", "value": ""}]})
    with pytest.raises(ValueError, match="never changes"):
        assistant_safety.check_actions(request, [UiAction(type="set_control", target="p", value="1")])
    # Opening a page is not a change.
    assistant_safety.check_actions(request, [UiAction(type="navigate", target="data.filter")])


def test_a_plan_aimed_at_a_stripped_pipeline_control_changes_nothing(assistant_rig):
    view = _with_pipeline(_coverage_view())
    plan = json.dumps({"task": "ui", "actions": [{"type": "set_control", "target": "loc", "value": "0.75"}]})
    with pytest.raises(ValueError):
        assistant_rig.run([plan], message="set the localization probability cutoff to 0.75", view=view)


# --- native tools ---------------------------------------------------------

def _tool_turns(monkeypatch, turns):
    seen = []

    def turn(request, messages, tools, **kwargs):
        seen.append({"messages": json.loads(json.dumps(messages)), "tools": tools, **kwargs})
        name, arguments = turns.pop(0)
        return "glm5", {"content": "", "tool_calls": [{"id": f"c{len(seen)}", "type": "function",
                                                        "function": {"name": name, "arguments": json.dumps(arguments)}}]}
    monkeypatch.setattr(assistant, "native_tools_supported", lambda request: True)
    monkeypatch.setattr(assistant, "assistant_tool_turn", turn)
    return seen


def test_an_advanced_model_reads_previews_then_finishes_with_tools(advanced, monkeypatch):
    seen = _tool_turns(monkeypatch, [
        ("preview_styles", {"styles": [{"element": "title", "property": "size", "operation": "set", "value": "huge"}]}),
        ("apply_styles", {"styles": [{"element": "title", "property": "size", "operation": "set", "value": "14"}],
                          "designNote": "A 14 pt title reads first."}),
    ])
    result = advanced.run([], message="make the title 14", view=_coverage_view())
    assert _targets(result) == {"title": "14"} and advanced.calls == []
    names = {tool["function"]["name"] for tool in seen[0]["tools"]}
    assert {"read_results", "preview_styles", "apply_styles", "ask_user"} <= names
    tool_reply = seen[1]["messages"][-1]
    assert tool_reply["role"] == "tool" and "problem" in tool_reply["content"]


def test_a_tool_plan_passes_the_same_checks_as_a_json_plan(advanced, monkeypatch):
    # An element the plot does not have is refused exactly as in the JSON plan.
    # It goes back to the model once; a second miss is refused.
    bad = ("apply_styles", {"styles": [{"element": "volcano points", "property": "size", "value": "9"}]})
    _tool_turns(monkeypatch, [bad, bad])
    with pytest.raises(ValueError, match="unavailable or ambiguous"):
        advanced.run([], message="make the points bigger", view=_coverage_view())


def test_tools_cannot_reach_pipeline_settings(advanced, monkeypatch):
    seen = _tool_turns(monkeypatch, [("ask_user", {"clarification": "pipeline"})])
    result = advanced.run([], message="normalize the data with median", view=_with_pipeline(_coverage_view()))
    schema = json.dumps(seen[0]["tools"])
    assert "Normalization" not in schema and "Localization probability" not in schema
    assert result.needsClarification and "never changes" in result.answer


def test_a_server_without_tools_falls_back_to_the_json_plan(advanced, monkeypatch):
    from app.services.chat_tools import NativeToolsUnavailable

    monkeypatch.setattr(assistant, "native_tools_supported", lambda request: True)
    def refuse(*args, **kwargs):
        raise NativeToolsUnavailable("no tools")
    monkeypatch.setattr(assistant, "assistant_tool_turn", refuse)
    plan = json.dumps({"task": "ui", "styles": [{"element": "title", "property": "size", "value": "14"}]})
    assert _targets(advanced.run([plan], message="make the title 14", view=_coverage_view())) == {"title": "14"}


def test_tool_definitions_follow_the_turns_schema():
    call = assistant._build_planner_call(AssistantRequest(message="make the title bold", view=_coverage_view()))
    tools = assistant_tools.definitions(call.schema, call.tasks, ["nature"])
    text = json.dumps(tools)
    assert "$ref" not in text
    apply_styles = next(tool for tool in tools if tool["function"]["name"] == "apply_styles")
    elements = apply_styles["function"]["parameters"]["properties"]["styles"]["items"]["properties"]["element"]["enum"]
    assert "title" in elements


# --- review, speed, budgets -------------------------------------------------

def test_an_advanced_batch_is_reviewed_once_in_the_picture(advanced, monkeypatch):
    seen = []
    def complete(request, instruction, data, **kwargs):
        seen.append((instruction, kwargs))
        styles = [{"element": "title", "property": "size", "value": "14"}] if not request.reviewing else \
            [{"element": "x ticks", "property": "size", "value": "8"}]
        return "glm5", json.dumps({"task": "ui", "styles": styles})
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    first = assistant.assistant_step(AssistantRequest(message="make the title 14", view=_coverage_view(), plotImage=IMAGE))
    assert first.finished and first.reviewAfter
    review = assistant.assistant_step(AssistantRequest(message="make the title 14", view=_coverage_view(), plotImage=IMAGE,
                                                       reviewing=True, receipts=['Set Title / Size to "14".']))
    assert "Review step" in seen[-1][0] and seen[-1][1].get("image") == IMAGE
    assert review.finished and not review.reviewAfter and _targets(review) == {"xt": "8"}


def test_no_review_without_an_image_or_for_application_changes(advanced, monkeypatch):
    monkeypatch.setattr(assistant, "assistant_completion", lambda *a, **k: (
        "glm5", json.dumps({"task": "ui", "styles": [{"element": "title", "property": "size", "value": "14"}]})))
    assert not assistant.assistant_step(AssistantRequest(message="make the title 14", view=_coverage_view())).reviewAfter
    bars = assistant.assistant_step(AssistantRequest(message="make the bars black", view=_coverage_view(), plotImage=IMAGE))
    assert bars.finished and not bars.reviewAfter


def test_styling_asks_for_high_reasoning_effort_on_advanced_models(advanced, monkeypatch):
    efforts = []
    def complete(request, instruction, data, **kwargs):
        efforts.append(kwargs.get("effort"))
        return "glm5", json.dumps({"task": "ui", "styles": [{"element": "title", "property": "size", "value": "14"}]})
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    assistant.assistant_step(AssistantRequest(message="make the title 14", view=_coverage_view()))
    assert efforts == ["high"]


def test_budgets_grow_with_an_advanced_models_window(monkeypatch):
    assert assistant_profiles.scaled_budgets("extended", 131072) == (12, 6000, 40000)
    assert assistant_profiles.scaled_budgets("extended", 16384)[2] == assistant_profiles.TIERS["extended"].evidence
    assert assistant_profiles.scaled_budgets("compact", 131072) == (2, 600, 3500)
    assert assistant_profiles.input_limit("extended", 131072) > 24_000 == assistant_profiles.input_limit("compact", 131072)
    monkeypatch.setattr(assistant, "_resolve_chat_model", lambda *a: "glm5")
    monkeypatch.setattr(assistant, "model_capability",
                        lambda *a: SimpleNamespace(contextTier="extended", contextWindow=131072))
    assert assistant._execution_profile(AssistantRequest(message="x", view={"module": "qc.cv"}))[1:] == (12, 6000)


# --- answers: comparisons ----------------------------------------------------

@pytest.mark.parametrize("sentence,kept", [
    ("A has more detected proteins than B.", True),
    ("B has more detected proteins than A.", False),
    ("A (366.5) is lower than B (330.5).", False),
    ("Counts decreased from 317 to 380.", False),
])
def test_a_comparison_must_point_the_way_the_evidence_does(sentence, kept):
    evidence = ["condition_stats|name=A|mean=366.50|median=366.50", "condition_stats|name=B|mean=330.50|median=330.50",
                "sample_values|values=317;380"]
    _, removed = assistant_prose.verify(sentence, evidence, "")
    assert (removed == 0) is kept


# --- styles across plots -----------------------------------------------------

def test_saving_and_applying_styles_needs_no_model(assistant_rig):
    saved = assistant_rig.run([], message='save this style as "lab figure"', view=_coverage_view())
    assert saved.actions[0].type == "save_style" and saved.actions[0].value == "lab figure" and saved.finished
    applied = assistant_rig.run([], message="apply the lab figure style to all plots", view=_coverage_view(),
                                savedStyles=["lab figure"])
    assert json.loads(applied.actions[0].value) == {"name": "lab figure", "scope": "all"}
    here = assistant_rig.run([], message="use my lab figure style", view=_coverage_view(), savedStyles=["lab figure"])
    assert json.loads(here.actions[0].value)["scope"] == "this"
    assert assistant_rig.calls == []


def test_a_journal_style_for_all_plots_is_applied_here_then_copied(assistant_rig):
    first = assistant_rig.run([], message="make all my plots Nature style", view=_coverage_view())
    assert first.actions and not first.finished and all(action.type == "set_control" for action in first.actions)
    second = assistant_rig.run([], message="make all my plots Nature style", view=_coverage_view(),
                               receipts=['Set Title / Size to "7".'])
    assert second.actions[0].type == "apply_style" and json.loads(second.actions[0].value)["scope"] == "all"


# --- progress -----------------------------------------------------------------

def test_progress_is_readable_and_holds_no_content(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services import assistant_progress

    monkeypatch.setenv("COPYLOT_AI_MODE", "1")
    assistant_progress.update("step-12345678", "thinking", 640)
    with TestClient(app) as client:
        state = client.get("/api/chat/assistant-progress/step-12345678")
        assert state.json()["phase"] == "thinking" and state.json()["tokens"] == 640
        assert client.get("/api/chat/assistant-progress/bad id").status_code in (400, 404)


def test_progress_ids_are_isolated_between_sessions(monkeypatch):
    from app.services import assistant_progress
    from app.services.session_context import reset_session_id, set_session_id

    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    first = set_session_id("progress-owner-one")
    try:
        assistant_progress.update("shared-progress-id", "thinking", 640)
        second = set_session_id("progress-owner-two")
        try:
            assert assistant_progress.read("shared-progress-id")["phase"] == "unknown"
            assistant_progress.next_call("shared-progress-id")
            assistant_progress.update("shared-progress-id", "answering", 10)
        finally:
            reset_session_id(second)
        assert assistant_progress.read("shared-progress-id")["tokens"] == 640
        assert assistant_progress.read("shared-progress-id")["calls"] == 0
    finally:
        reset_session_id(first)


# --- second glm5 round (2026-10-08) ----------------------------------------------

def test_a_style_the_plot_lacks_goes_back_to_the_model_once_with_what_it_has(advanced, monkeypatch):
    seen = _tool_turns(monkeypatch, [
        ("apply_styles", {"styles": [{"element": "title", "property": "size", "value": "14"},
                                     {"element": "title", "property": "glow", "value": "true"}]}),
        ("apply_styles", {"styles": [{"element": "title", "property": "size", "value": "14"}],
                          "designNote": "The title cannot glow here."}),
    ])
    result = advanced.run([], message="make the title 14 and make it glow", view=_coverage_view())
    problem = json.loads(seen[1]["messages"][-1]["content"])
    assert problem["applied"] is False and "title has: size" in problem["problem"]
    assert _targets(result) == {"title": "14"} and "cannot glow" in result.answer


@pytest.mark.parametrize("message", ["the sample names at the bottom are hard to read, can you fix that?",
                                     "Mach die Schrift bitte größer", "the x labels overlap"])
def test_readability_and_other_languages_hand_over_sizes(assistant_rig, message):
    view = _coverage_view()
    xt = next(control for control in view["controls"] if control["id"] == "xt")
    request = AssistantRequest(message=message, view=view)
    control = next(control for control in request.view.controls if control.id == xt["id"])
    assert assistant._scope_problem(request, UiAction(type="set_control", target="xt", value="12"), control) is None
    plain = AssistantRequest(message="make the title red", view=view)
    assert assistant._scope_problem(plain, UiAction(type="set_control", target="xt", value="12"), control)


def test_a_sample_against_its_condition_mean_is_a_derived_figure():
    evidence = ["condition_stats|name=B|mean=330.50|median=330.50", "sample_values|condition=B|values=B_1=344;B_4=317"]
    _, removed = assistant_prose.verify("B_4 sits about 13.5 proteins below its condition's mean (330.5).", evidence, "")
    assert removed == 0
    _, removed = assistant_prose.verify("B_4 sits about 21 proteins below its condition's mean.", evidence, "")
    assert removed == 1
