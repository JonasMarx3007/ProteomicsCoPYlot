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
    first = assistant.assistant_step(AssistantRequest(message="make the plot look nicer", view=_coverage_view(), plotImage=IMAGE))
    assert first.finished and first.reviewAfter
    small = assistant.assistant_step(AssistantRequest(message="make the title 14", view=_coverage_view(), plotImage=IMAGE))
    assert small.finished and not small.reviewAfter  # one explicit edit is not worth a look at the picture
    review = assistant.assistant_step(AssistantRequest(message="make the plot look nicer", view=_coverage_view(), plotImage=IMAGE,
                                                       reviewing=True, receipts=['Set Title / Size to "14".']))
    assert "Review step" in seen[-1][0] and seen[-1][1].get("image") == IMAGE
    assert review.finished and not review.reviewAfter and _targets(review) == {"xt": "8"}


def test_no_review_without_an_image_or_for_application_changes(advanced, monkeypatch):
    monkeypatch.setattr(assistant, "assistant_completion", lambda *a, **k: (
        "glm5", json.dumps({"task": "ui", "styles": [{"element": "title", "property": "size", "value": "14"}]})))
    assert not assistant.assistant_step(AssistantRequest(message="make the title 14", view=_coverage_view())).reviewAfter
    bars = assistant.assistant_step(AssistantRequest(message="make the bars black", view=_coverage_view(), plotImage=IMAGE))
    assert bars.finished and not bars.reviewAfter


def test_no_reasoning_effort_is_requested_by_default(advanced, monkeypatch):
    # glm5 took over 172 s with "high" and 69 s without for the same restyle (2026-10-09).
    efforts = []
    def complete(request, instruction, data, **kwargs):
        efforts.append(kwargs.get("effort"))
        return "glm5", json.dumps({"task": "ui", "styles": [{"element": "title", "property": "size", "value": "14"}]})
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    assistant.assistant_step(AssistantRequest(message="make the title 14", view=_coverage_view()))
    assert efforts == [None]


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


# --- live round with personas (2026-10-08) ---------------------------------------

def test_a_model_that_read_the_results_writes_its_own_answer_in_two_calls(advanced, monkeypatch):
    from app.schemas.assistant import Evidence

    advanced.evidence = [Evidence(tool="current_plot", status="available", text="coverage_summary|detected_mean=7407|total=7490")]
    seen = _tool_turns(monkeypatch, [
        ("read_results", {}),
        ("answer", {"task": "current_plot", "text": "Each sample detects about 7407 of 7490 proteins. "
                                                     "That is 9999 more than expected."}),
    ])
    result = advanced.run([], message="what is this bar chart telling me?", view=_coverage_view())
    assert advanced.calls == []  # no evidence-choice and no separate writing call
    assert "7407 of 7490" in result.answer and "9999" not in result.answer and "left out 1 sentence" in result.answer
    assert "7490" in seen[1]["messages"][-1]["content"]  # the model read what it is checked against


def test_reading_another_modules_method_needs_no_navigation(advanced, monkeypatch):
    _tool_turns(monkeypatch, [("read_results", {"module": "qc.cv", "kind": "method"}),
                              ("answer", {"task": "help", "module": "qc.cv", "text": "The CV is the SD over the mean."})])
    result = advanced.run([], message="what is a CV plot?", view=_coverage_view())
    assert advanced.plans[0].task == "help" and advanced.plans[0].module == "qc.cv"
    assert result.answer == "The CV is the SD over the mean."


def test_native_result_evidence_matches_the_text_actually_sent(advanced, monkeypatch):
    from app.schemas.assistant import Evidence

    advanced.evidence = [Evidence(tool="current_plot", status="available", text="coverage|total=7407\n" + "x" * 100 + "|hidden=9999")]
    monkeypatch.setattr(assistant, "_evidence_limit", lambda profile: 40)
    seen = _tool_turns(monkeypatch, [("read_results", {}),
                                    ("answer", {"task": "current_plot", "text": "There are 7407 proteins."})])
    result = advanced.run([], message="what does this chart show?", view=_coverage_view())
    assert "9999" not in seen[1]["messages"][-1]["content"]
    assert result.evidence[0].status == "partial"
    assert "9999" not in result.evidence[0].text


def test_results_that_need_another_pages_selections_open_that_page(assistant_rig):
    from app.schemas.assistant import Evidence

    assistant_rig.evidence = [Evidence(tool="current_plot", status="unavailable", text="volcano_data|status=incomplete_parameters")]
    view = {**_coverage_view(), "destinations": {"qc.coverage": "QC", "stats.volcano": "Statistical Analysis / Volcano"}}
    plan = json.dumps({"task": "current_plot", "module": "stats.volcano"})
    choice = json.dumps({"source": "result:stats.volcano", "query": ""})
    result = assistant_rig.run([plan, choice], message="WT vs GRK volcano, welch: how many go up?", view=view)
    assert [(a.type, a.target) for a in result.actions] == [("navigate", "stats.volcano")]
    assert result.explainAfterChanges and not result.finished


def test_a_closing_answer_after_changes_just_finishes(advanced, monkeypatch):
    _tool_turns(monkeypatch, [("answer", {"task": "ui", "text": "Done, the plot is cleaned up."})])
    result = advanced.run([], message="make it cleaner", view=_coverage_view(), receipts=['Set Title / Size to "14".'])
    assert result.actions == [] and "Done" not in result.answer


def test_presentation_wording_hands_over_the_look():
    from app.services import assistant_presets

    for message in ["can you make this plot look cleaner for my lab meeting?", "tidy this up for my talk",
                    "Mach den Plot bitte schöner"]:
        assert assistant_presets.improvement_requested(message), message
    assert not assistant_presets.improvement_requested("make the title red")


def test_many_left_alone_notes_become_one_sentence():
    notes = [f"No numeric adjustment was requested for {label}; I left it unchanged."
             for label in ("Title / Size", "Legend / Text size", "X axis / X tick label size")]
    notes.append("The request does not name condition 'WT', so I left Names and colours / Condition colors / WT unchanged.")
    (summary,) = assistant._summarised(notes)
    assert summary.startswith("I kept 4 settings") and "Condition colors / WT" in summary
    assert assistant._summarised(notes[:2]) == notes[:2]


def test_an_answer_about_a_module_that_needs_its_selections_opens_it(advanced, monkeypatch):
    from app.schemas.assistant import Evidence

    advanced.evidence = [Evidence(tool="current_plot", status="available", text="volcano_data|status=incomplete_parameters")]
    _tool_turns(monkeypatch, [("read_results", {"module": "stats.volcano"}),
                              ("answer", {"task": "current_plot", "module": "stats.volcano",
                                          "text": "Open the volcano and set the conditions first."})])
    view = {**_coverage_view(), "destinations": {"qc.coverage": "QC", "stats.volcano": "Volcano"}}
    result = advanced.run([], message="how many proteins are up in GRK vs WT?", view=view)
    assert [(a.type, a.target) for a in result.actions] == [("navigate", "stats.volcano")] and result.explainAfterChanges


def test_rounded_figures_shares_and_textbook_constants_are_confirmed():
    evidence = ["phospho_coverage_sample|condition=WT|sample=WT_1|class_i=5021|not_class_i=6188|total=11209"]
    keep = ["WT_1 would lose about 6,200 sites.", "That leaves roughly 5,000-5,100 sites.",
            "About 55% of its detections are not class I.", "A box shows the median and the middle 50% of values."]
    drop = ["WT_1 would lose 6,200 sites.", "It would lose about 7,000 sites."]
    for sentence in keep:
        assert assistant_prose.verify(sentence, evidence, "")[1] == 0, sentence
    for sentence in drop:
        assert assistant_prose.verify(sentence, evidence, "")[1] == 1, sentence


def test_a_lead_in_without_what_it_introduced_is_dropped():
    text, removed = assistant_prose.verify("WT_1 detects 11209 sites.\n\nThe loss would be:\n- 9,000 sites.\n\nThat is all.",
                                           ["total=11209"], "")
    assert removed == 1 and "would be:" not in text and "That is all." in text


def test_numbers_glued_to_evidence_keys_are_known():
    _, removed = assistant_prose.verify("A site is class I at a probability of at least 0.75.",
                                        ["phospho_coverage_class_rule|class_i=PTM_localization_greater_than_or_equal_to_0.75"], "")
    assert removed == 0


def test_identifier_digits_do_not_validate_unrelated_result_numbers():
    text, removed = assistant_prose.verify("There are 12345 significant proteins.",
                                           ["feature=P12345|sample=run_12345|color=#123456"], "")
    assert removed == 1 and not text


def test_a_feature_named_in_the_last_message_can_be_shown_as_it():
    request = AssistantRequest(message="show me the plot for it", view={"module": "singleProtein.boxplot"},
                               messages=[{"role": "user", "content": "how does CCN1 look across my samples?"},
                                         {"role": "assistant", "content": "CCN1 is higher in GRK."},
                                         {"role": "user", "content": "show me the plot for it"}])
    assert assistant._grounded("CCN1_HUMAN", request)
    assert not assistant._grounded("ANXA3_HUMAN", request)
    assert not assistant._grounded("CCN1_HUMAN", request.model_copy(update={"message": "show me a plot"}))


def test_german_numbers_and_abbreviations_are_read_as_written():
    evidence = ["volcano_rank|name=CCN1_HUMAN|log2fc=2.75|padj=2.6e-07", "volcano_summary|tested=7435|up=53",
                "volcano_comparison|condition1=GRK|condition2=WT"]
    text, removed = assistant_prose.verify(
        "In dieser Einstellung (GRK vs. WT) wurden 7.435 Proteine getestet, 53 sind hochreguliert. "
        "CCN1_HUMAN hat log2 FC 2,75 bei p 2,6e-07.", evidence, "")
    assert removed == 0 and "GRK vs. WT" in text
    assert assistant_prose.verify("CCN1_HUMAN hat log2 FC 3,75.", evidence, "")[1] == 1


def test_what_is_missing_from_a_total_is_a_derived_figure():
    evidence = ["coverage_overview|total_features=7490", "condition_stats|name=WT|mean=7406.60|min=7402|max=7410"]
    assert assistant_prose.verify("WT misses about 83 proteins per sample, between 80 and 88.", evidence, "")[1] == 0
    assert assistant_prose.verify("WT misses 120 proteins per sample.", evidence, "")[1] == 1


def test_unrelated_settings_are_not_parts_of_a_total():
    evidence = ["coverage_overview|total_features=1000|seed=123"]
    assert assistant_prose.verify("There are 877 missing proteins.", evidence, "")[1] == 1


def test_page_labels_are_literal_text():
    request = AssistantRequest(message="help", view={"module": "qc.cv", "destinations": {"qc.cv": r"CV \ details"}})
    assert assistant._page_names("Open qc.cv.", request) == "Open CV \\ details."


def test_a_condition_name_is_never_taken_for_its_colour():
    from app.schemas.assistant import UiControl
    from app.services.assistant_plot_parts import identity

    names = UiControl(id="n", label="Names and colours / Condition names / GRK", type="text", value="")
    colours = UiControl(id="c", label="Names and colours / Condition colors / GRK", type="color", value="#000000")
    assert identity(names) == ("condition:GRK", "label") and identity(colours) == ("condition:GRK", "color")


def test_a_threshold_phrase_is_not_a_comparison_and_list_numbers_stay_with_their_item():
    evidence = ["ora_warnings|messages=55 of 7,490 rows were not tested: fewer than 2 values",
                "ora_term|rank=7|name=heparin binding|term_size=50|intersection_size=10|gene_ratio=0.19"]
    text, removed = assistant_prose.verify(
        "55 of 7,490 rows were not tested because they had fewer than 2 values.\n7. Heparin binding: 10 of 50, ratio 0.19\n"
        "8. Heparin binding again: ratio 0.25", evidence, "")
    assert removed == 1 and "7. Heparin binding" in text and "\n8." not in text


def _volcano_view(first="WT", second="WT"):
    def select(id_, label, value):
        return {"id": id_, "label": label, "type": "select", "value": value, "options": ["WT", "GRK"], "permission": "confirm"}
    return {"module": "stats.volcano", "controls": [select("c1", "Condition 1", first), select("c2", "Condition 2", second)]}


@pytest.mark.parametrize("message", ["which phosphosites go up the most in GRK?", "what is higher in GRK?"])
def test_an_up_in_question_sets_the_only_possible_contrast(assistant_rig, message):
    result = assistant_rig.run([], message=message, view=_volcano_view())
    assert {a.target: a.value for a in result.actions} == {"c1": "GRK"} and result.explainAfterChanges  # c2 is already WT
    assert assistant_rig.calls == []


def test_an_existing_contrast_with_that_condition_is_kept():
    request = AssistantRequest(message="which proteins go up in GRK?", view=_volcano_view("WT", "GRK"))
    assert assistant._implied_contrast_plan(request) is None
    three = {**_volcano_view(), "controls": [{**control, "options": ["WT", "GRK", "KO"]} for control in _volcano_view()["controls"]]}
    assert assistant._implied_contrast_plan(AssistantRequest(message="what is up in GRK?", view=three)) is None


def test_a_question_asked_with_ask_user_is_asked(advanced, monkeypatch):
    _tool_turns(monkeypatch, [("ask_user", {"clarification": "condition",
                                            "question": "Shall I compare GRK against WT?"})])
    result = advanced.run([], message="which proteins differ?", view=_volcano_view())
    assert result.needsClarification and "GRK against WT" in result.answer


def test_between_two_conditions_sets_them_in_the_order_written():
    plan = assistant._implied_contrast_plan(AssistantRequest(
        message="how many replicates would I need to find more hits between GRK and WT?", view=_volcano_view()))
    assert [(a["target"], a["value"]) for a in plan["actions"]] == [("c1", "GRK")]


# --- tool-loop tolerance (2026-10-13) --------------------------------------------
# What mid-size models get wrong in the tool protocol, each answered with one
# deterministic correction instead of a refusal. None of it adds reach: a
# finishing call still goes through the same validation.

def _raw_turns(monkeypatch, replies):
    """Like _tool_turns, but each reply is a full assistant message (prose, several calls, ...)."""
    seen = []

    def turn(request, messages, tools, **kwargs):
        seen.append({"messages": json.loads(json.dumps(messages)), "tools": tools})
        return "qwen", replies.pop(0)
    monkeypatch.setattr(assistant, "native_tools_supported", lambda request: True)
    monkeypatch.setattr(assistant, "assistant_tool_turn", turn)
    return seen


def _call(name, arguments, id_="c"):
    return {"id": id_, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def test_prose_after_reading_the_results_is_the_answer(advanced, monkeypatch):
    from app.schemas.assistant import Evidence

    advanced.evidence = [Evidence(tool="current_plot", status="available", text="coverage_summary|detected_mean=7407|total=7490")]
    seen = _raw_turns(monkeypatch, [
        {"content": "", "tool_calls": [_call("read_results", {})]},
        {"content": "Each sample detects about 7407 of 7490 proteins. That is 9999 more than expected."},
    ])
    result = advanced.run([], message="what is this bar chart telling me?", view=_coverage_view())
    assert len(seen) == 2  # no reminder call: the prose was checked as the answer
    assert "7407 of 7490" in result.answer and "9999" not in result.answer


def test_prose_without_a_tool_gets_one_reminder_then_the_application_answers(advanced, monkeypatch):
    seen = _raw_turns(monkeypatch, [{"content": "Sure! Let me look at that."},
                                    {"content": "The coverage looks fine to me."}])
    written = json.dumps({"answer": "Each bar is one sample's number of detected proteins."})
    result = advanced.run([written], message="what is this bar chart telling me?", view=_coverage_view())
    assert seen[1]["messages"][-1]["role"] == "user" and "tool call, not text" in seen[1]["messages"][-1]["content"]
    assert len(seen) == 2 and result.answer.startswith("Each bar")  # written by the application


def test_results_read_in_the_same_reply_as_the_answer_are_read_first(advanced, monkeypatch):
    from app.schemas.assistant import Evidence

    advanced.evidence = [Evidence(tool="current_plot", status="available", text="coverage_summary|detected_mean=7407|total=7490")]
    _raw_turns(monkeypatch, [{"content": "", "tool_calls": [
        _call("answer", {"task": "current_plot", "text": "About 7407 of 7490 proteins per sample."}, "a"),
        _call("read_results", {}, "b")]}])
    result = advanced.run([], message="why are some samples lower than others?", view=_coverage_view())
    assert result.answer.startswith("About 7407 of 7490") and result.evidence


def test_a_misspelt_tool_goes_back_once_with_the_tool_names(advanced, monkeypatch):
    seen = _raw_turns(monkeypatch, [
        {"content": "", "tool_calls": [_call("apply_style", {"styles": []})]},
        {"content": "", "tool_calls": [_call("apply_styles", {"styles": [
            {"element": "title", "property": "size", "value": "14"}]})]},
    ])
    result = advanced.run([], message="make the title 14", view=_coverage_view())
    error = json.loads(seen[1]["messages"][-1]["content"])["error"]
    assert "no tool named 'apply_style'" in error and "apply_styles" in error
    assert _targets(result) == {"title": "14"}


def test_cut_off_arguments_go_back_once_then_are_refused(advanced, monkeypatch):
    broken = {"id": "c", "type": "function", "function": {"name": "apply_styles", "arguments": '{"styles": [{"elem'}}
    _raw_turns(monkeypatch, [{"content": "", "tool_calls": [broken]}, {"content": "", "tool_calls": [broken]}])
    with pytest.raises(ValueError, match="not valid JSON"):
        advanced.run([], message="make the title 14", view=_coverage_view())


def test_a_correction_answers_every_call_in_the_batch(advanced, monkeypatch):
    seen = _raw_turns(monkeypatch, [
        {"content": "", "tool_calls": [_call("apply_style", {}, "bad"), _call("apply_styles", {}, "later")]},
        {"content": "", "tool_calls": [_call("apply_styles", {"styles": [
            {"element": "title", "property": "size", "value": "14"}]}, "fixed")]},
    ])
    result = advanced.run([], message="make the title 14", view=_coverage_view())
    replies = [item for item in seen[1]["messages"] if item["role"] == "tool"]
    assert [item["tool_call_id"] for item in replies] == ["bad", "later"]
    assert "Not executed" in replies[1]["content"]
    assert _targets(result) == {"title": "14"}


@pytest.mark.parametrize("given", ["qc.CV", "cv", "CV Plot"])
def test_a_module_name_that_identifies_one_module_is_read_as_it(given):
    view = {**_coverage_view(), "destinations": {"qc.coverage": "QC Pipeline / Coverage Plot", "qc.cv": "QC Pipeline / CV Plot"}}
    request = AssistantRequest(message="x", view=view)
    module, note = assistant._resolve_module(request, given, ["qc.coverage", "qc.cv", "stats.volcano", "workflow.overview"])
    assert module == "qc.cv" and "read as qc.cv" in note


def test_an_unknown_module_is_refused_in_the_tool_result_not_read_as_the_open_plot(advanced, monkeypatch):
    from app.schemas.assistant import Evidence

    advanced.evidence = [Evidence(tool="current_plot", status="available", text="coverage_summary|total=7490")]
    seen = _raw_turns(monkeypatch, [
        {"content": "", "tool_calls": [_call("read_results", {"module": "kinase.activity"})]},
        {"content": "", "tool_calls": [_call("read_results", {})]},
        {"content": "", "tool_calls": [_call("answer", {"task": "current_plot", "text": "7490 proteins in total."})]},
    ])
    result = advanced.run([], message="why are some samples lower than others?", view=_coverage_view())
    first = seen[1]["messages"][-1]["content"]
    assert first.startswith("Unknown module 'kinase.activity'") and "qc.coverage" in first and "7490" not in first
    assert result.answer.startswith("7490 proteins")


def test_a_model_that_keeps_reading_is_told_to_finish_before_the_last_round(advanced, monkeypatch):
    reads = [{"content": "", "tool_calls": [_call("find_settings", {"word": "title"})]} for _ in range(5)]
    seen = _raw_turns(monkeypatch, [*reads, {"content": "", "tool_calls": [_call("apply_styles", {"styles": [
        {"element": "title", "property": "size", "value": "14"}]})]}])
    result = advanced.run([], message="make the title 14", view=_coverage_view())
    assert _targets(result) == {"title": "14"}
    assert sum("Finish now" in m.get("content", "") for m in seen[-1]["messages"] if m["role"] == "user") == 1


# --- first Claude API round (2026-10-13) -----------------------------------------

def test_a_project_answer_the_model_wrote_is_kept_and_checked(advanced, monkeypatch):
    """claude-sonnet-5-5 answered a cutoff question correctly with task=project_state; the
    application threw the text away and rewrote it without the key sentence."""
    from app.schemas.assistant import Evidence

    advanced.evidence = [Evidence(tool="project_state", status="available",
                                  text="localization|cutoff=0|sites=11916|at_0.75=5224|at_0.9=3989")]
    seen = _raw_turns(monkeypatch, [
        {"content": "", "tool_calls": [_call("read_results", {"module": "", "kind": "results"})]},
        {"content": "", "tool_calls": [_call("answer", {"task": "project_state", "text":
            "The cutoff is 0, so all 11916 sites are in use. At 0.75, 5224 sites would stay. At 0.8, 4000 would stay."})]},
    ])
    result = advanced.run([], message="which localization cutoff is active and how many sites survive 0.75?",
                          view=_coverage_view())
    assert len(seen) == 2 and advanced.calls == []  # no third, application-written call
    assert "5224 sites would stay" in result.answer and "4000" not in result.answer


def test_visibility_given_as_a_string_boolean_is_accepted():
    from app.schemas.assistant import StyleEdit
    from app.services import assistant_styling

    request = AssistantRequest(message="hide the grid", view=_coverage_view())
    resolved = assistant_styling.resolve(request, [StyleEdit(element="frame and grid / grid lines", property="show", value="false")])
    assert [(action.target, action.value) for action in resolved] == [("grid", False)]


def test_a_view_request_answered_from_the_opened_page_keeps_the_explanation(advanced, monkeypatch):
    """"show me the PCA, do my groups separate?" is a UI request; after opening the page the
    model read the results and answered. The answer tool was not offered in that step and
    Haiku invented it (2026-10-13); now it is offered and the text is the explanation."""
    from app.schemas.assistant import Evidence

    advanced.evidence = [Evidence(tool="current_plot", status="available", text="pca|pc1_variance=49.65|pc2_variance=9.14")]
    seen = _raw_turns(monkeypatch, [
        {"content": "", "tool_calls": [_call("read_results", {"kind": "results"})]},
        {"content": "", "tool_calls": [_call("answer", {"task": "current_plot", "text": "PC1 explains 49.65% and separates the groups."})]},
    ])
    view = {**_coverage_view(), "module": "qc.pca", "destinations": {"qc.pca": "QC Pipeline / PCA"}}
    result = advanced.run([], message="show me the PCA plot", view=view, receipts=["Opened QC Pipeline / PCA."])
    assert "answer" in {tool["function"]["name"] for tool in seen[0]["tools"]}
    assert result.answer.startswith("PC1 explains 49.65%") and not result.actions


def test_asking_which_contrast_after_reading_a_waiting_page_opens_that_page(advanced, monkeypatch):
    """From the coverage page, "which phosphosites go up most in GRK?" has no change_view tool;
    Haiku read the volcano (waiting for a contrast) and asked which one (2026-10-13). The page is
    opened instead; the question's wording sets the contrast there."""
    from app.schemas.assistant import Evidence

    advanced.evidence = [Evidence(tool="volcano_data", status="unavailable", text="volcano_data|status=incomplete_parameters")]
    _tool_turns(monkeypatch, [("read_results", {"module": "stats.volcano", "kind": "results"}),
                              ("ask_user", {"clarification": "condition", "question": "Shall I compare GRK against WT?"})])
    view = {**_coverage_view(), "destinations": {"qc.coverage": "QC", "stats.volcano": "Volcano"}}
    result = advanced.run([], message="which phosphosites go up most in GRK? top 5", view=view)
    assert [(a.type, a.target) for a in result.actions] == [("navigate", "stats.volcano")] and result.explainAfterChanges
    assert not result.needsClarification


def test_a_hit_the_assistant_just_listed_can_be_shown_as_the_first_one():
    history = [{"role": "user", "content": "give me the three strongest hits"},
               {"role": "assistant", "content": "1. CCN1_HUMAN: log2 FC 2.75\n2. LRC58_HUMAN: 2.20\n3. ANXA3_HUMAN: 1.75"}]
    request = AssistantRequest(message="and how does the first one look across my samples?",
                               view={"module": "singleProtein.boxplot"},
                               messages=[*history, {"role": "user", "content": "and how does the first one look across my samples?"}])
    assert assistant._grounded("CCN1_HUMAN", request)
    assert not assistant._grounded("LRC58_HUMAN", request)
    second = request.model_copy(update={"message": "show the second one"})
    assert assistant._grounded("LRC58_HUMAN", second) and not assistant._grounded("CCN1_HUMAN", second)
    assert not assistant._grounded("NFM_HUMAN", request)  # never listed
    # Without a reference to the list, a listed name is still not the user's choice.
    assert not assistant._grounded("CCN1_HUMAN", request.model_copy(update={"message": "show me a protein boxplot"}))


def test_a_reply_written_without_reading_is_checked_not_dropped(advanced, monkeypatch):
    """"export the summary table as excel": the model answered without reading anything and the
    application showed the module's method text instead (Haiku, 2026-10-13)."""
    _raw_turns(monkeypatch, [{"content": "", "tool_calls": [_call("answer", {"task": "help", "text":
        "I can't run exports from here. The Download CSV button above the table saves it; 9999 rows are shown."})]}])
    result = advanced.run([], message="ok then export the summary table as excel for me", view=_coverage_view())
    assert result.answer.startswith("I can't run exports from here") and "9999" not in result.answer


def test_choosing_a_tile_type_on_the_canvas_does_not_finish_the_request(advanced, monkeypatch):
    view = {"module": "analysis.canvas", "destinations": {"analysis.canvas": "Analysis"}, "controls": [
        {"id": "add", "label": "+ Add Plot", "type": "button", "value": ""},
        {"id": "kind", "label": "New tile type", "type": "select", "value": "volcano",
         "options": ["volcano", "proteinBoxplot"], "optionLabels": {"volcano": "Volcano", "proteinBoxplot": "Protein Boxplot"}}]}
    plan = json.dumps({"task": "ui", "actions": [{"type": "set_control", "target": "kind", "value": "proteinBoxplot"}]})
    result = advanced.run([plan], message="put a boxplot of CCN1 on the analysis canvas", view=view)
    assert _targets(result) == {"kind": "proteinBoxplot"} and not result.finished


def test_a_batch_leaving_the_named_protein_unplaced_is_not_finished(advanced, monkeypatch):
    view = {"module": "analysis.canvas", "destinations": {"analysis.canvas": "Analysis"}, "controls": [
        {"id": "src", "label": "Tile 1: proteinBoxplot / Protein source", "type": "select", "value": "list",
         "options": ["list", "manual"], "optionLabels": {"list": "List", "manual": "Manual input"}}]}
    plan = json.dumps({"task": "ui", "actions": [{"type": "set_control", "target": "src", "value": "manual"}]})
    result = advanced.run([plan], message="put a boxplot of CCN1 on the analysis canvas", view=view,
                          receipts=["Opened Analysis.", "+ Add Plot: completed."])
    assert _targets(result) == {"src": "manual"} and not result.finished
    # Once the name is placed, the same kind of batch is complete.
    placed = {**view, "controls": [*view["controls"], {"id": "p", "label": "Tile 1: proteinBoxplot / Protein or gene",
                                                      "type": "text", "value": "CCN1_HUMAN"}]}
    result = advanced.run([plan], message="put a boxplot of CCN1 on the analysis canvas", view=placed,
                          receipts=["Opened Analysis.", "+ Add Plot: completed."])
    assert result.finished


def test_a_german_correlation_rounded_to_three_decimals_is_confirmed():
    """"r = 0,994" for mean_r=0.9938: a comma after a lone zero is a decimal comma, not a thousands group."""
    evidence = ["correlation_group_summary|group=within_condition|mean_r=0.9938|min_r=0.9910|max_r=0.9951", "total=11916"]
    text, removed = assistant_prose.verify("Innerhalb der Bedingungen: mittleres r = 0,994 (Bereich 0,991–0,995).", evidence, "")
    assert removed == 0 and "0,994" in text
    text, removed = assistant_prose.verify("Alle 11,916 Sites sind drin.", evidence, "")
    assert removed == 0  # a thousands group still reads as one


@pytest.mark.parametrize("message, expected", [
    ("what changes in signalling when GRK is present?", [("c1", "GRK")]),
    ("we knocked in GRK and I expect CCN1 and CCN2 to change", [("c1", "GRK")]),
    ("how does the proteome respond to WT?", [("c2", "GRK")]),  # the fixture starts at WT vs WT
    ("what differs between WT and GRK cells?", [("c2", "GRK")]),  # the existing between-rule
    ("what changes when GRK is present compared with WT?", None),  # both named without an order: not guessed
    ("GRK is the treatment", None),  # no change wording
])
def test_treatment_wording_implies_the_two_condition_contrast(message, expected):
    plan = assistant._implied_contrast_plan(AssistantRequest(message=message, view=_volcano_view()))
    assert (None if plan is None else [(a["target"], a["value"]) for a in plan["actions"]]) == expected


def test_a_named_protein_question_read_from_a_waiting_page_opens_that_page(advanced, monkeypatch):
    """"We knocked in GRK; does the data support a change in CCN1?" from the coverage page: the model
    read the volcano (waiting for its contrast) and answered that it could not say (2026-10-13)."""
    from app.schemas.assistant import Evidence

    advanced.evidence = [Evidence(tool="volcano_data", status="unavailable", text="volcano_data|status=incomplete_parameters")]
    _tool_turns(monkeypatch, [("read_results", {"module": "stats.volcano", "kind": "results"}),
                              ("answer", {"task": "current_plot", "text": "I can't yet say whether CCN1 changed."})])
    view = {**_coverage_view(), "destinations": {"qc.coverage": "QC", "stats.volcano": "Volcano"}}
    result = advanced.run([], message="We knocked in GRK and expect CCN1 to change. Does the data support this?", view=view)
    assert [(a.type, a.target) for a in result.actions] == [("navigate", "stats.volcano")] and result.explainAfterChanges


def test_an_unset_contrast_takes_the_treatment_named_earlier_in_the_conversation():
    history = [{"role": "user", "content": "we knocked in GRK and expect CCN1 to change; does the data support that?"},
               {"role": "assistant", "content": "Yes: CCN1 log2FC 2.75."},
               {"role": "user", "content": "run the GO enrichment on the up set"}]
    request = AssistantRequest(message="run the GO enrichment on the up set", view=_volcano_view(), messages=history)
    plan = assistant._implied_contrast_plan(request)
    assert [(a["target"], a["value"]) for a in plan["actions"]] == [("c1", "GRK")]
    # A contrast already set is never overridden from history.
    assert assistant._implied_contrast_plan(AssistantRequest(message=request.message, view=_volcano_view("WT", "GRK"),
                                                             messages=history)) is None


@pytest.mark.parametrize("value, message, expected", [
    ("P08174~CD55_Y224_M1", "show me CD55 Y224 on its own", True),
    ("P08174~CD55_Y224_M1", "show me CD55 S101", False),
    ("CCN1_HUMAN", "how does CCN1 look?", True),
    ("P12345;P23456", "show me the group", False),
])
def test_a_site_named_by_its_parts_is_grounded(value, message, expected):
    assert assistant._grounded(value, AssistantRequest(message=message, view={"module": "singleProtein.boxplot"})) is expected


def test_an_identifier_the_assistant_tied_to_the_users_name_is_grounded():
    """"GRK2 (listed as ARBK1_HUMAN)" in the last reply, then "show the plot for GRK2" (GRK project,
    2026-10-13): the uploaded identifier follows from the assistant's own answer, not from a guess."""
    history = [{"role": "user", "content": "look up GRK2 and GRK6 in dQ0 vs C0"},
               {"role": "assistant", "content": "- GRK2 (listed as ARBK1_HUMAN): 0 values in dQ0, 6 in C0.\n"
                                                "- GRK6 (listed as F8W9W2_HUMAN): the same pattern."}]
    view = {"module": "singleProtein.boxplot"}
    assert assistant._grounded("ARBK1_HUMAN", AssistantRequest(message="show the boxplot for GRK2", view=view, messages=history))
    assert not assistant._grounded("F8W9W2_HUMAN", AssistantRequest(message="show the boxplot for GRK2", view=view, messages=history))
    assert not assistant._grounded("ARBK1_HUMAN", AssistantRequest(message="show the boxplot for the kinase", view=view, messages=history))
    assert not assistant._grounded("ARBK1_HUMAN", AssistantRequest(message="show the boxplot for GRK2", view=view))
    same_sentence = [{"role": "assistant", "content": "GRK2 (listed as ARBK1_HUMAN) differs from GRK6 (listed as F8W9W2_HUMAN)."}]
    assert not assistant._grounded("F8W9W2_HUMAN", AssistantRequest(message="show the boxplot for GRK2", view=view, messages=same_sentence))


@pytest.mark.parametrize("message, expected", [
    ("Volcano GRK vs WT, Welch, Publikationsstil, und die drei stärksten Hits beschriftet", "publication"),
    ("mach die Abbildung publikationsreif", "publication"),
    ("eine Abbildung im Nature-Stil", "nature"),
    ("what is a paper?", None),
])
def test_german_publication_wording_names_the_preset(message, expected):
    from app.services import assistant_presets

    assert assistant_presets.requested(message)[0] == expected


def test_read_results_looks_up_named_features_of_the_volcano(example_project):
    """"Are ANXA1 and ANXA3 affected, and how strongly compared to CCN1?": the ranked lists show
    ten per direction, so a named protein needs its own row (2026-10-13)."""
    request = AssistantRequest(message="are ANXA1 and ANXA3 affected?", view={
        "module": "stats.volcano", "workflow": "protein",
        "mode": {"kind": "protein", "condition1": "GRK", "condition2": "WT"}})
    found = assistant._read_for_tools(request, {"kind": "results", "lookup": "ANXA1, CCN1, NOTAGENE"}, "compact")
    text = "\n".join(item.text for item in found)
    assert "volcano_lookup|query=CCN1|term=CCN1" in text and "log2FC=2.75" in text
    assert "volcano_lookup|query=ANXA1" in text
    assert "volcano_lookup_not_found|queries=NOTAGENE" in text


def test_read_results_lookup_reports_rows_the_test_could_not_use(example_project):
    """"Is GRK2 actually absent in the knockout?" A protein missing in every replicate of one
    condition never reaches the volcano; the lookup reports its value counts instead (2026-10-13)."""
    request = AssistantRequest(message="is CSTA absent in WT?", view={
        "module": "stats.volcano", "workflow": "protein",
        "mode": {"kind": "protein", "condition1": "GRK", "condition2": "WT"}})
    found = assistant._read_for_tools(request, {"kind": "results", "lookup": "CSTA"}, "compact")
    text = "\n".join(item.text for item in found)
    assert "volcano_lookup_untested|query=CSTA|term=CYTA_HUMAN|n_GRK=3|n_WT=0|mean_GRK=7.49|" in text
    assert "reason=fewer than 2 values in WT|note=values_count_per_condition_0_means_not_detected" in text
    assert "volcano_lookup_not_found" not in text


def test_lookup_queries_keep_a_gene_and_its_site_together():
    """"MAP4K4 S1045, REPS1 S143" asked for two sites, not four names (GRK, 2026-10-13)."""
    from app.services.ai_functions import _lookup_pattern, _lookup_queries

    assert _lookup_queries("C2orf49 S146, MAP4K4 S1045; ANXA1 ANXA3 GRK2,S6") == ["C2orf49 S146", "MAP4K4 S1045", "ANXA1", "ANXA3", "GRK2", "S6"]
    assert _lookup_pattern("MAP4K4 S1045").search("O95819~MAP4K4_S1045_M1")
    assert not _lookup_pattern("MAP4K4 S1045").search("O95819~MAP4K4_S757_M1")
    assert not _lookup_pattern("MAP4K4 S1045").search("O95819~MAP4K4_S10450_M1")
    assert _lookup_pattern("ANXA1").search("ANXA1_HUMAN") and not _lookup_pattern("ANXA1").search("ANXA10_HUMAN")


def test_read_results_can_read_another_contrast_and_set_two_contrasts_against_each_other(example_project):
    """"Up after stimulation in the parental cells but not in the knockout" (GRK, 2026-10-14): one
    read-only call; the application matches the rows, the open plot is unchanged."""
    from app.services.ai_functions import _contrast_pair

    assert _contrast_pair("C5 vs C0") == ("C5", "C0") and _contrast_pair("dQ5 versus dQ0") == ("dQ5", "dQ0")
    assert _contrast_pair("C5,C0") == ("C5", "C0") and _contrast_pair("C0 vs C0") is None and _contrast_pair("C5") is None
    request = AssistantRequest(message="which hits of WT vs GRK are not hits the other way?", view={
        "module": "stats.volcano", "workflow": "protein",
        "mode": {"kind": "protein", "condition1": "GRK", "condition2": "WT"}})
    found = assistant._read_for_tools(request, {"kind": "results", "conditions": "WT vs GRK", "versus": "GRK vs WT"}, "compact")
    text = "\n".join(item.text for item in found)
    assert "volcano_comparison|condition1=WT|condition2=GRK" in text and "volcano_read_override|" in text
    assert "volcano_versus|a=WT_vs_GRK|b=GRK_vs_WT|" in text
    assert "volcano_versus_up|a_up=9|also_up_in_b=0|not_significant_in_b=0|opposite_in_b=9|untested_in_b=0|absent_in_b=0" in text
    assert "volcano_versus_down|a_down=53|also_down_in_b=0|not_significant_in_b=0|opposite_in_b=53|" in text
    # Without an override the read is the open plot's own contrast.
    plain = "\n".join(item.text for item in assistant._read_for_tools(request, {"kind": "results"}, "compact"))
    assert "volcano_comparison|condition1=GRK|condition2=WT" in plain and "volcano_versus" not in plain
    # An unknown condition is an error line, never a silent substitute.
    bad = "\n".join(item.text for item in assistant._read_for_tools(request, {"kind": "results", "conditions": "GRK vs NOPE"}, "compact"))
    assert "volcano_data|status=error" in bad
    for conditions in ("GRK", "WT vs WT"):
        malformed = "\n".join(item.text for item in assistant._read_for_tools(request, {"conditions": conditions}, "compact"))
        assert "volcano_data|status=error" in malformed
    assert _contrast_pair("Treated cells vs. Vehicle cells") == ("Treated cells", "Vehicle cells")


def test_cross_contrast_matching_never_collapses_repeated_gene_labels(monkeypatch):
    import pandas as pd
    from app.services import ai_functions, stats_tools

    a = pd.DataFrame({"GeneNames": ["GENE", "GENE"], "PTM_Collapse_key": ["GENE_S1", "GENE_S2"],
                      "log2FC": [2., 3.], "adj_pval": [.001, .001], "significance": ["Upregulated"] * 2})
    b = a.iloc[::-1].copy()
    b["significance"] = ["Not significant", "Upregulated"]
    monkeypatch.setattr(stats_tools, "_volcano_dataframe", lambda **kwargs: ("data", "GeneNames", b, []))
    kwargs = dict(kind="phospho", identifier="genes", p_value_threshold=.05, log2fc_threshold=1.,
                  test_type="unpaired", use_uncorrected=False, data_source="data", a_pair=("A", "ref"))
    text = "\n".join(ai_functions._volcano_contrast_difference(a, "GeneNames", ("B", "ref"), **kwargs))
    assert "also_up_in_b=1|not_significant_in_b=1" in text
    assert "volcano_a_specific_up|term=GENE_S2|" in text
    b.drop(columns="PTM_Collapse_key", inplace=True)
    assert "no_unique_shared_row_identifier" in "\n".join(ai_functions._volcano_contrast_difference(a, "GeneNames", ("B", "ref"), **kwargs))


def test_cross_contrast_enrichment_uses_only_jointly_testable_rows(monkeypatch):
    import pandas as pd
    from app.services import ai_functions, stats_tools

    a = pd.DataFrame({"GeneNames": [f"G{i}" for i in range(8)], "log2FC": [2.] * 8,
                      "adj_pval": [.001] * 8, "significance": ["Upregulated"] * 8})
    b = a.iloc[:7].copy()
    b.loc[6, "significance"] = "Unavailable"
    seen = []
    monkeypatch.setattr(stats_tools, "_volcano_dataframe", lambda **kwargs: ("data", "GeneNames", b, []))
    monkeypatch.setattr(stats_tools, "run_enrichment_from_list", lambda request: (seen.append(request) or SimpleNamespace(terms=[])))
    lines = ai_functions._volcano_contrast_difference(a, "GeneNames", ("B", "ref"), kind="protein", identifier="genes",
        p_value_threshold=.05, log2fc_threshold=1., test_type="paired", use_uncorrected=False,
        data_source="data", a_pair=("A", "ref"), enrich=True, organism="mouse")
    assert seen and seen[0].backgroundGenes == [f"G{i}" for i in range(6)]
    assert seen[0].organism == "mouse"
    assert "different complete pairs" in "\n".join(lines)
    assert "|direction=" not in "\n".join(lines)
    seen.clear()
    lines = ai_functions._volcano_contrast_difference(a, "GeneNames", ("B", "ref"), kind="protein", identifier="genes",
        p_value_threshold=.05, log2fc_threshold=1., test_type="unpaired", use_uncorrected=False,
        data_source="data", a_pair=("A", "ref"), enrich=True)
    assert not seen and "no organism was assumed" in "\n".join(lines)


def test_a_fold_change_said_from_a_log2_fold_change_is_confirmed():
    evidence = ["volcano_lookup|query=ANXA3|term=ANXA3_HUMAN|log2FC=1.75|adj_p_value=6.612e-08"]
    kept, removed = assistant_prose.verify("ANXA3: log2FC 1.75 (about 3.4-fold), adjusted p 6.6e-08.", evidence, "")
    assert removed == 0 and "3.4-fold" in kept
    assert assistant_prose.verify("ANXA3 is about 5-fold up.", evidence, "")[1] == 1


def test_styling_that_names_another_page_is_not_appearance_only():
    """"Make the dQ0 vs C0 volcano publication ready" from the coverage page (GRK, 2026-10-14)."""
    destinations = {"qc.coverage": "QC / Coverage Plot - counts", "stats.volcano": "Statistical Analysis / Volcano Plot - fold change",
                    "singleProtein.heatmap": "Single Protein / Heatmap", "completeness.heatmap": "Completeness / Heatmap"}
    message = "Make the dQ0 vs C0 volcano publication ready: label the three strongest hits, Nature style."
    assert assistant._appearance_only(AssistantRequest(message=message, view={"module": "stats.volcano", "destinations": destinations}))
    assert not assistant._appearance_only(AssistantRequest(message=message, view={"module": "qc.coverage", "destinations": destinations}))
    # A page name shared by several destinations does not navigate away from one of them.
    heat = "make the heatmap Nature style"
    assert assistant._appearance_only(AssistantRequest(message=heat, view={"module": "completeness.heatmap", "destinations": destinations}))
    assert not assistant._appearance_only(AssistantRequest(message=heat, view={"module": "qc.coverage", "destinations": destinations}))
    assert assistant._appearance_only(AssistantRequest(message="make the title bold", view={"module": "qc.coverage", "destinations": destinations}))


def test_a_gap_between_two_boxplot_medians_is_confirmed():
    """"C: 6.22 at 0 min, 8.46 at 5 min (about +2.2)" was removed: the boxplot table's keys are
    capitalised (GRK project, 2026-10-14)."""
    evidence = ["single_protein_boxplot_table_row|rank=1|Condition=C0|N=6|Mean=6.04|Median=6.22|Q1=6.12|Q3=6.28|Min=4.85|Max=6.58\n"
                "single_protein_boxplot_table_row|rank=2|Condition=C5|N=6|Mean=8.46|Median=8.46|Q1=8.43|Q3=8.50|Min=8.39|Max=8.53"]
    kept, removed = assistant_prose.verify("C: 6.22 at 0 min, 8.46 at 5 min (about +2.2).", evidence, "")
    assert removed == 0 and "+2.2" in kept
    assert assistant_prose.verify("C: 6.22 at 0 min, 8.46 at 5 min (about +3.1).", evidence, "")[1] == 1


def test_a_total_of_two_confirmed_figures_in_the_same_sentence_is_confirmed():
    """"352 sites are not significant in the knockout: 174 up and 178 down" was removed as a whole
    (GRK project, 2026-10-14); a sum or gap of two confirmed figures in the sentence is the reader's."""
    evidence = ["volcano_versus_up|a_up=483|also_up_in_b=265|not_significant_in_b=174|opposite_in_b=1|untested_in_b=43|absent_in_b=0\n"
                "volcano_versus_down|a_down=400|also_down_in_b=197|not_significant_in_b=178|opposite_in_b=0|untested_in_b=25|absent_in_b=0"]
    kept, removed = assistant_prose.verify("352 sites respond in parental but not in the knockout: 174 up and 178 down.", evidence, "")
    assert removed == 0 and "352" in kept
    assert assistant_prose.verify("68 sites (43 up, 25 down) could not be tested in the knockout.", evidence, "")[1] == 0
    # Two unconfirmed figures do not confirm each other, and a wrong total is still wrong.
    assert assistant_prose.verify("360 sites respond: 174 up and 178 down.", evidence, "")[1] == 1
    assert assistant_prose.verify("352 sites respond: 170 up and 182 down.", evidence, "")[1] == 1


@pytest.mark.parametrize("a, b, relation, expected", [
    (1.27, -1.15, "chained", "toward_reference"),
    (-1.12, -1.00, "chained", "further_from_reference"),           # SCOT1: down in dQ0, further down in R20
    (2.42, 1.91, "shared_reference", "toward_reference"),
    (2.0, 2.1, "shared_reference", "further_from_reference"),
    (2.0, -2.0, "shared_reference", "opposite_side_of_reference"),
    (2.0, 0.3, "shared_reference", "toward_reference"),
    (2.0, 2.0, "shared_reference", "same_point_estimate"),
    (2.0, -2.0, "chained", "at_reference_point_estimate"),
])
def test_direction_words_say_where_contrast_b_puts_a_row(a, b, relation, expected):
    from app.services.ai_functions import _reference_direction

    assert _reference_direction(a, b, relation) == expected


def test_versus_reports_named_rows_in_b_with_direction_words_and_enriches_derived_sets(monkeypatch):
    """"Does GRK2 re-expression revert the baseline hits?" (GRK, 2026-10-14): the model misread the
    sign of R20 vs dQ0 once; now the application writes the direction, and the gene sets that
    differ between the contrasts are tested for GO over-representation."""
    import pandas as pd
    from app.services import ai_functions, stats_tools

    ribosome = ["RPL3", "RPL4", "RPL5", "RPL6", "RPL7", "RPL8", "RPL9", "RPL10", "RPL11", "RPL12", "RPS3", "RPS4X", "RPS5", "RPS6", "RPS7"]
    others = ["ACTB", "GAPDH", "TUBB", "VIM", "HSPA8", "EEF1A1", "PKM", "ENO1", "LDHA", "ALDOA", "TPI1", "PGK1", "MYH9", "FLNA", "ANXA2",
              "ATP5F1A", "SLC25A5", "HSP90AA1", "CALM1", "YWHAZ", "PRDX1", "SOD1"]
    genes = ribosome + ["CCN1", "IRS2", "OXCT1"] + others
    frame_a = pd.DataFrame({"GeneNames": genes, "log2FC": [1.5] * 15 + [1.3, -1.2, -1.1] + [0.1] * 22,
                            "adj_pval": [0.001] * 18 + [0.5] * 22,
                            "significance": ["Upregulated"] * 16 + ["Downregulated"] * 2 + ["Not significant"] * 22})
    frame_b = frame_a.copy()
    frame_b["log2FC"] = [1.6] * 15 + [-1.15, -1.0, 0.0] + [0.1] * 22      # ribosome unchanged; CCN1 reverts, IRS2 further
    frame_b["adj_pval"] = [0.001] * 15 + [0.2, 0.01, 0.9] + [0.5] * 22
    frame_b["significance"] = ["Upregulated"] * 15 + ["Not significant", "Downregulated", "Not significant"] + ["Not significant"] * 22
    monkeypatch.setattr(stats_tools, "_volcano_dataframe", lambda **kwargs: ("data", "GeneNames", frame_b, []))
    lines = ai_functions._volcano_contrast_difference(
        frame_a, "GeneNames", ("R20", "dQ0"), kind="protein", identifier="workflow", p_value_threshold=0.05,
        log2fc_threshold=1.0, test_type="unpaired", use_uncorrected=False, data_source="filtered", a_pair=("dQ0", "C0"),
        lookup=["CCN1", "IRS2"], enrich=True, organism="human")
    text = "\n".join(lines)
    assert "volcano_versus|a=dQ0_vs_C0|b=R20_vs_dQ0|" in text and "reference=C0|direction_words=b_is_measured_from_dQ0" in text
    assert "volcano_versus_up|a_up=16|also_up_in_b=15|not_significant_in_b=1|" in text
    assert "volcano_lookup_in_b|query=CCN1|term=CCN1|a_log2FC=1.30|a_significance=Upregulated|b_log2FC=-1.15|b_adj_p=2.000e-01|b_significance=Not significant|direction=toward_reference" in text
    assert "volcano_lookup_in_b|query=IRS2|term=IRS2|" in text and "b_significance=Downregulated|direction=further_from_reference" in text
    assert "volcano_a_specific_up|term=CCN1|" in text and "direction=toward_reference" in text
    assert "Significant in A but not B does not establish a difference" in text
    assert "volcano_versus_enrichment|method=over_representation_hypergeometric_BH|background=genes_with_usable_tests_in_both_contrasts|background_genes=40|" in text
    assert "volcano_versus_enriched|set=a_specific_up|genes=1|status=too_few_genes" in text
    shared = [line for line in lines if line.startswith("volcano_versus_enriched|set=shared_up|genes=15|rank=")]
    assert len(shared) == 6 and all("|overlap=15|" in line and "|adj_p=" in line for line in shared)
