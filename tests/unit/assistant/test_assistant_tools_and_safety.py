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
    from app.services.assistant_styling import identity

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
