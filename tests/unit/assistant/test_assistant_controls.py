import json

import pandas as pd
import pytest
from app.schemas.assistant import AssistantRequest, Evidence
from app.services import canvas_focus, scientific_assistant as assistant
from app.services.assistant_routing import (
    appearance_only_request,
    canvas_add_request,
    explicit_selection,
    feature_request,
    feature_request_mode,
    planner_tasks,
    rephrase_request,
)
from assistant_support import PLAN, _control, _labels_view, _site_view, _styling_view, _volcano_view


def _feature_view(value="K0"):
    return {"module": "singleProtein.boxplot", "mode": {"kind": "phospho"},
            "controls": [{"id": "site", "label": "Protein / Site", "type": "select", "value": value,
                          "options": [f"K{i}" for i in range(40)], "optionCount": 80, "permission": "view"}]}


@pytest.fixture
def sites(monkeypatch):
    frame = pd.DataFrame({
        "PTM_Collapse_key": ["K2", "K3", "K7", "K10", *[f"K7{i}" for i in range(10)]],
        "Protein_group": ["P1", "P1", "P3", "P10", *["P9"] * 10],
        "Gene_group": ["G1", "G1", "G3", "G10", *["G9"] * 10],
    })
    monkeypatch.setattr(canvas_focus, "select_matrix", lambda kind, source: ("data", frame, pd.DataFrame()))
    return frame


@pytest.mark.parametrize("value", [45, 30.5])
@pytest.mark.parametrize("target", ["rotation", "control:0"])
def test_semantic_numeric_values_resolve_live_control_ids(assistant_rig, value, target):
    run = assistant_rig.run
    result = run([json.dumps({"task": "ui", "styles": [
        {"element": "x ticks", "property": "rotation", "value": str(value)},
    ]})], message=f"Rotate the x-axis tick labels to {value} degrees.",
        view={"module": "singleProtein.boxplot",
              "controls": [_control(target, "X axis / X tick label rotation", min=-90, max=90)]})
    assert result.actions[0].value == str(value)
    assert result.actions[0].target == target


@pytest.mark.parametrize("value,type_,target", [("91", "number", "x ticks"), (45, "text", "x ticks"),
                                               (True, "number", "x ticks"), ("45", "number", "unknown")])
def test_numeric_coercion_does_not_bypass_control_validation(assistant_rig, value, type_, target):
    run = assistant_rig.run
    with pytest.raises(ValueError):
        run([json.dumps({"task": "ui", "styles": [
            {"element": target, "property": "rotation", "value": value},
        ]})], message="Rotate the x-axis tick labels to 45 degrees.",
            view={"module": "singleProtein.boxplot",
                  "controls": [_control("rotation", "X axis / X tick label rotation", type=type_, min=-90, max=90)]})


def test_a_redundant_navigation_no_longer_refuses_the_welch_change(assistant_rig):
    run = assistant_rig.run
    plan = {"task": "ui", "actions": [{"type": "set_control", "target": "test", "value": "unpaired_welch"},
                                      {"type": "navigate", "target": "stats.volcano", "value": ""}]}
    result = run([json.dumps(plan)], message="Change the test to Welch and explain the result.", view=_volcano_view())
    assert [(a.type, a.value) for a in result.actions] == [("set_control", "unpaired_welch")]
    assert result.explainAfterChanges  # 4 of 8 models omitted the explanation flag


def test_a_stray_setter_after_navigation_waits_for_the_new_page(assistant_rig):
    run = assistant_rig.run
    view = {**_volcano_view(), "destinations": {"singleProtein.boxplot": "Boxplot"}}
    plan = {"task": "ui", "actions": [{"type": "navigate", "target": "singleProtein.boxplot", "value": ""},
                                      {"type": "set_control", "target": "test", "value": "paired"}]}
    result = run([json.dumps(plan)], message="Open the protein boxplot and explain what it shows.", view=view)
    assert [(a.type, a.target) for a in result.actions] == [("navigate", "singleProtein.boxplot")]
    assert result.explainAfterChanges


def test_normalisation_never_invents_or_repairs_an_action(assistant_rig):
    run = assistant_rig.run
    plan = {"task": "ui", "actions": [{"type": "set_control", "target": "test", "value": "welch"}]}
    with pytest.raises(ValueError, match="Invalid value"):
        run([json.dumps(plan)], message="Use Welch", view=_volcano_view())


@pytest.mark.parametrize("message,token", [
    ("Now select phosphosite K23, not K17, and rotate the x-axis tick labels to 30 degrees.", "K23"),
    ("Select phosphosite K79.", "K79"),
    ("Choose protein P0;P1 please", "P0;P1"),
    ("Find and select that phosphosite.", None),
    ("Do not select K3.", None),
    ("Select K2 and select K3", None),
    ("Show MAPK1 in the protein boxplot and briefly tell me which group is higher.", "MAPK1"),
    ("Don't show MAPK1 in the protein boxplot", None),
    ("Show MAPK1 and AKT1 in the protein boxplot", None),
    ("Select the phosphosite for protein P1.", None),
])
def test_explicit_selection_reads_exactly_one_named_identifier(message, token):
    assert explicit_selection(message) == token


def test_the_named_site_is_selected_before_the_styling_part(monkeypatch):
    monkeypatch.setattr(assistant, "assistant_completion", lambda *a, **k: pytest.fail("No model call for the selection"))
    request = AssistantRequest(message="Now select phosphosite K23, not K17, and rotate the x-axis tick labels to 30 degrees.",
                               view=_site_view("K17"))
    result = assistant.assistant_step(request)
    assert result.model == "application"
    assert [(a.type, a.target, a.value) for a in result.actions] == [("set_control", "site", "K23")]


@pytest.mark.parametrize("message,view", [
    ("Select phosphosite K79.", _site_view("K79")),              # already selected
    ("Select phosphosite K99.", _site_view("K17")),              # not an option
    ("Select protein K23.", _site_view("K17")),                  # level mismatch (phospho view)
    ("Keep the view unchanged and select K23.", _site_view("K17")),
])
def test_the_selection_shortcut_steps_aside_when_not_exact(monkeypatch, message, view):
    monkeypatch.setattr(assistant, "_resolve_chat_model", lambda *args: "synthetic")
    assert assistant._explicit_selection_response(AssistantRequest(message=message, view=view), 1) is None


def test_a_sample_rename_is_never_applied_to_a_condition(assistant_rig):
    run = assistant_rig.run
    plan = {'task': 'ui', 'styles': [{'element': 'condition:A', 'property': 'color', 'value': '#ff0000'}, {'element': 'condition:A', 'property': 'label', 'value': 'Control 1'}, {'element': 'x ticks', 'property': 'rotation', 'value': '45'}]}
    message = 'Use the advanced plot options to make condition A red (#ff0000), rename sample A1 to Control 1, and set the x-axis tick labels to 45 degrees.'
    result = run([json.dumps(plan)], message=message, view=_labels_view())
    assert [a.target for a in result.actions] == ['colA', 'rot']
    assert 'sample' in result.answer and 'Condition names / A' in result.answer and (not result.needsClarification)


def test_a_rename_of_only_a_sample_is_reported_not_substituted(assistant_rig):
    run = assistant_rig.run
    plan = {'task': 'ui', 'styles': [{'element': 'condition:A', 'property': 'label', 'value': 'Control 1'}]}
    result = run([json.dumps(plan)], message='Rename sample A1 to Control 1.', view=_labels_view())
    assert not result.actions and result.needsClarification
    assert 'left that control unchanged' in result.answer
    assert 'No sample-level control' not in result.answer


def test_dpi_is_not_a_rotation(assistant_rig):
    run = assistant_rig.run
    plan = {'task': 'ui', 'styles': [{'element': 'plot', 'property': 'dpi', 'value': '30'}]}
    result = run([json.dumps(plan)], message='Rotate the x-axis tick labels to 30 degrees.', view=_labels_view())
    assert not result.actions and 'DPI' in result.answer


@pytest.mark.parametrize('message,value,allowed', [('Make condition A red (#ff0000), rename sample A1 to Control 1.', '#ff0000', False), ('Make condition A red.', 'red', False), ('Rename condition A to #ff0000.', '#ff0000', True), ('Use Treatment as the display name for condition A.', 'Treatment', True)])
def test_condition_colour_cannot_be_substituted_for_a_display_name(assistant_rig, monkeypatch, message, value, allowed):
    monkeypatch.setattr(assistant, '_simple_style_plan', lambda request: None)
    run = assistant_rig.run
    result = run([json.dumps({'task': 'ui', 'styles': [{'element': 'condition:A', 'property': 'label', 'value': value}]})], message=message, view=_labels_view())
    assert bool(result.actions) is allowed
    if not allowed:
        assert 'does not request a name change' in result.answer or 'No rename was requested' in result.answer


def test_width_is_not_a_sample_label(assistant_rig):
    run = assistant_rig.run
    plan = {'task': 'ui', 'styles': [{'element': 'plot', 'property': 'width', 'value': '1'}]}
    result = run([json.dumps(plan)], message='Rename sample A1 to Control 1.', view=_labels_view())
    assert not result.actions


def test_an_unnamed_condition_is_left_alone_but_all_conditions_is_allowed(assistant_rig):
    run = assistant_rig.run
    plan = {'task': 'ui', 'styles': [{'element': 'condition:A', 'property': 'color', 'value': '#ff0000'}, {'element': 'condition:B', 'property': 'color', 'value': '#ff0000'}]}
    result = run([json.dumps(plan)], message='Make condition A red.', view=_labels_view())
    assert [a.target for a in result.actions] == ['colA']
    result = run([json.dumps(plan)], message='Make all conditions red.', view=_labels_view())
    assert [a.target for a in result.actions] == ['colA', 'colB']


def test_the_planner_is_told_what_was_left_undone(assistant_rig):
    run, calls = assistant_rig.run, assistant_rig.calls
    run(['{"task":"ui","actions":[]}'], message="Rename sample A1 to Control 1 and rotate labels 45 degrees.",
        view=_labels_view(), notes=["Sample renaming is unavailable here."], receipts=["Changed rotation."])
    assert calls[0]["notDone"] == ["Sample renaming is unavailable here."]


def test_a_colour_put_into_a_name_says_where_it_belongs(assistant_rig):
    run = assistant_rig.run
    plan = {'task': 'ui', 'styles': [{'element': 'condition:A', 'property': 'label', 'value': '#ff0000'}]}
    result = run([json.dumps(plan)], message='Make condition A red (#ff0000).', view=_labels_view())
    assert not result.actions and 'Condition names / A unchanged' in result.answer


@pytest.mark.parametrize("message,allowed", [
    ("Open the volcano for Treated versus Vehicle and tell me what it means.", True),
    ("Please set the comparison to Vehicle vs Treated.", True),
    ("Is Treated versus Vehicle significant?", False),
    ("Do not change the comparison to Treated versus Vehicle.", False),
    ("Use Missing versus Vehicle.", False),
])
def test_named_contrast_respects_explicit_live_options(message, allowed):
    from app.schemas.assistant import AssistantRequest, UiAction
    from app.services.scientific_assistant import _named_contrast_plan, _scope_problem
    request=AssistantRequest(message=message,view={"module":"stats.volcano","controls":[
        {"id":"first","label":"Condition 1","type":"select","permission":"view","value":"Treated","options":["Vehicle","Treated"]},
        {"id":"second","label":"Condition 2","type":"select","permission":"view","value":"Treated","options":["Vehicle","Treated"]}]})
    plan=_named_contrast_plan(request, include_satisfied=True)
    assert bool(plan) == allowed
    assert _named_contrast_plan(request.model_copy(update={"answerOnly":True})) is None
    if plan:
        expected=next(action["value"] for action in plan["actions"] if action["target"]=="second")
        opposite="Vehicle" if expected=="Treated" else "Treated"
        assert _scope_problem(request,UiAction(type="set_control",target="second",value=opposite),request.view.controls[1])


def test_quoted_title_request_cannot_move_legend_or_invent_size():
    from app.schemas.assistant import AssistantRequest, UiAction
    from app.services.scientific_assistant import _scope_problem
    request=AssistantRequest(message='Highlight AKT1 and call the plot "Treatment comparison".',view={"module":"stats.volcano","controls":[
        {"id":"offset","label":"Legend / Legend Y offset (px)","type":"number","permission":"view","appearance":True,"value":"0"},
        {"id":"size","label":"Title / Size","type":"number","permission":"view","appearance":True,"value":"12"},
        {"id":"title","label":"Title / Text","type":"text","permission":"view","appearance":True,"value":""}]})
    for control in request.view.controls[:2]:
        assert _scope_problem(request,UiAction(type="set_control",target=control.id,value="25"),control)
    assert _scope_problem(request,UiAction(type="set_control",target="title",value="Treatment comparison"),request.view.controls[2]) is None


@pytest.mark.parametrize("message", ["make the legend smaller", "make the xlabel smaller", "make the title bigger",
                                    "change title size to 3", "Could you make the legend smaller?", "Make condition A red"])
def test_ordinary_styling_discovers_controls_and_preserves_selection(message):
    assert appearance_only_request(message)
    assert planner_tasks(message) == ["ui", "clarify"]


@pytest.mark.parametrize("message", ["Select K9 and make the title bigger", "Compare A and B and make the title bigger",
                                    "Make the p-value threshold smaller", "How can I make the title bigger?"])
def test_styling_scope_does_not_absorb_selection_science_or_advice(message):
    assert not appearance_only_request(message)


@pytest.mark.parametrize("message", ["using more natural langauge?", "Use plain English", "simpler words please",
                                     "Can you say that more simply?", "Could you put it more naturally?"])
def test_conversational_rephrasing(message):
    assert rephrase_request(message)


def test_plot_text_edit_is_not_answer_rephrasing():
    assert not rephrase_request("Change the title to plain English")


@pytest.mark.parametrize("message,value", [("Change title size to 3", "3"), ("Make the title bigger", "14.4"),
                                          ("Could you enlarge the plot heading?", "14.4")])
def test_single_numeric_style_uses_live_control_not_model_guess(message, value):
    request = AssistantRequest(message=message, view={"module":"qc.coverage",
        "controls":[{"id":"title", "label":"Title / Size", "type":"number", "value":"12",
                     "appearance":True, "permission":"view"}]})
    assert assistant._simple_style_plan(request)['actions'][0]['value'] == value


def test_numeric_style_does_not_target_scientific_controls():
    request = AssistantRequest(message="Make the title bigger", view={"module":"qc.coverage",
        "controls":[{"id":"title", "label":"Title / Size", "type":"number", "value":"12"}]})
    assert assistant._simple_style_plan(request) is None


def test_named_colour_targets_colour_not_name():
    from app.schemas.assistant import UiAction
    request = AssistantRequest(message="Make condition B blue.", view={"module":"qc.coverage", "controls":[
        {"id":"colour", "label":"Names and colours / Condition colors / B", "type":"color", "value":"#000000", "appearance":True, "permission":"view"},
        {"id":"name", "label":"Names and colours / Condition names / B", "type":"text", "value":"B", "appearance":True, "permission":"view"}]})
    assert assistant._simple_style_plan(request)['actions'] == [{'type':'set_control', 'target':'colour', 'value':'#0000ff'}]
    action = UiAction(type="set_control", target="name", value="#0000ff")
    assert assistant._scope_problem(request, action, request.view.controls[1])


def test_natural_rephrase_with_pronoun():
    assert rephrase_request("Say that in plain language.")


def test_relative_resize_runs_once_per_user_request(assistant_rig):
    run = assistant_rig.run
    result = run(['{"task":"ui","actions":[{"type":"set_control","target":"legend","value":"6"}]}'],
                 message="Make the legend smaller", receipts=['Set Legend / Text size to "8".'],
                 view={"module":"qc.coverage", "controls":[
                     {"id":"legend", "label":"Legend / Text size", "type":"number", "value":"8",
                      "appearance":True, "permission":"view"}]})
    assert not result.actions and not result.needsClarification


def test_relative_followup_retains_its_target_across_planner_steps(assistant_rig):
    run = assistant_rig.run
    result = run([], message="A little bigger again please.", receipts=['Set Title / Size to "16.8".'],
        conversationState={"request":"Make the title bigger", "module":"qc.coverage", "workflow":"protein",
                           "completed":['Set Title / Size to "14".'], "selections":[], "status":"completed"},
        view={"module":"qc.coverage", "workflow":"protein", "controls":[
            {"id":"title", "label":"Title / Size", "type":"number", "value":"16.8", "appearance":True, "permission":"view"},
            {"id":"axis", "label":"X axis / Axis label / Size", "type":"number", "value":"10", "appearance":True, "permission":"view"}]})
    assert not result.actions


def test_relative_followup_does_not_guess_between_two_changed_sizes(assistant_rig):
    run, calls = assistant_rig.run, assistant_rig.records
    result = run([], message="A little bigger again, please.",
        conversationState={"request":"Make the title bigger and legend smaller", "module":"qc.coverage", "workflow":"protein",
            "completed":['Set Title / Size to "14".', 'Set Legend / Text size to "8".'], "selections":[], "status":"completed"},
        view={"module":"qc.coverage", "workflow":"protein", "controls":[
            {"id":"title", "label":"Title / Size", "type":"number", "value":"14", "appearance":True, "permission":"view"},
            {"id":"legend", "label":"Legend / Text size", "type":"number", "value":"8", "appearance":True, "permission":"view"}]})
    assert result.needsClarification and not result.actions and not calls
    assert "Title / Size" in result.answer and "Legend / Text size" in result.answer


@pytest.mark.parametrize("include_query", [False, True])
def test_unknown_supplied_identifier_is_not_treated_as_missing_input(assistant_rig, include_query):
    run = assistant_rig.run
    plan = {"task":"clarify", "clarification":"entity", **({"query":"NOT_FOUND"} if include_query else {})}
    result = run([json.dumps(plan)],
        message="Show protein NOT_FOUND.", view={"module":"singleProtein.boxplot", "workflow":"protein", "controls":[
            {"id":"feature", "label":"Protein / Site", "type":"select", "value":"AKT1", "options":["AKT1","MAPK1"], "optionCount":2}]})
    assert result.needsClarification and not result.actions
    assert "NOT_FOUND" in result.answer and "current feature choices" in result.answer


@pytest.mark.parametrize("options,count,expected", [(["AKT1"],1,True), (["AKT1"],20,False), (["not_found"],1,False)])
def test_named_plot_unknown_requires_complete_choices(options, count, expected):
    request = AssistantRequest(message="Open the protein boxplot for NOT_FOUND.", view={
        "module":"singleProtein.boxplot", "workflow":"protein", "controls":[{
            "id":"feature", "label":"Protein / Site", "type":"select", "value":"AKT1",
            "options":options, "optionCount":count}]})
    result = assistant._explicit_selection_response(request, 1)
    assert bool(result and result.needsClarification) == expected


def test_negated_named_plot_does_not_select_a_feature():
    request = AssistantRequest(message="Do not open the protein boxplot for MAPK1.", view={
        "module":"singleProtein.boxplot", "workflow":"protein", "controls":[{
            "id":"feature", "label":"Protein / Site", "type":"select", "value":"AKT1",
            "options":["AKT1","MAPK1"], "optionCount":2}]})
    assert assistant._explicit_selection_response(request, 1) is None


def test_completed_named_plot_does_not_ask_model_for_identifier_again():
    request = AssistantRequest(message="Open the protein boxplot for MAPK1.", view={
        "module":"singleProtein.boxplot", "workflow":"protein", "controls":[{
            "id":"feature", "label":"Protein / Site", "type":"select", "value":"MAPK1",
            "options":["AKT1","MAPK1"], "optionCount":2}]})
    result = assistant._explicit_selection_response(request, 1)
    assert result is not None and not result.actions and not result.needsClarification
    assert "Already showing MAPK1" in result.answer


@pytest.mark.parametrize("preserve", ["Don't change the protein or groups.", "Keep the samples unchanged.", "Leave conditions alone."])
def test_preserving_entities_does_not_block_explicit_styling(preserve):
    from app.services.assistant_routing import appearance_only_request, requests_unchanged_view
    question = "Make the legend smaller and colour Treated #cc3300. " + preserve
    assert appearance_only_request(question)
    assert not requests_unchanged_view(question)
    assert requests_unchanged_view("Keep everything unchanged.")


@pytest.mark.parametrize("question,kind", [
    ("Show AKT1 on the canvas.", "protein"),
    ("Show phosphosite S42 on the canvas.", "phospho"),
    ("Show protein AKT1 on the canvas, not a phosphosite.", "protein"),
])
def test_canvas_scope_uses_requested_or_current_level(monkeypatch, question, kind):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    call = assistant.plan_request(AssistantRequest(message=question, view={"module":"qc.coverage", "workflow":"protein"}))
    assert call.schema["$defs"]["CanvasFocusRequest"]["properties"]["kind"]["enum"] == [kind]


@pytest.mark.parametrize("on_canvas", [False, True])
def test_canvas_keeps_referenced_contrast_order(monkeypatch, on_canvas):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("compact", 2, 600))
    selections = [{"label":"Condition 1", "value":"Treated"}, {"label":"Condition 2", "value":"Vehicle"}]
    controls = [{**item, "id":item["label"], "type":"select"} for item in selections]
    request = AssistantRequest(message="Show AKT1 on the canvas for these two conditions.",
        view={"module":"analysis.canvas" if on_canvas else "stats.volcano", "workflow":"protein", "controls":[] if on_canvas else controls},
        conversationState={"request":"Highlight AKT1", "module":"stats.volcano", "workflow":"protein",
                           "selections":selections, "completed":[], "status":"completed"})
    assert assistant._referenced_contrast(request) == ["Treated", "Vehicle"]
    call = assistant.plan_request(request)
    assert call.schema["$defs"]["CanvasFocusRequest"]["properties"]["conditions"]["enum"] == [["Treated", "Vehicle"]]
    assert assistant._referenced_contrast(request.model_copy(update={"message":"Show AKT1 for Vehicle versus Treated."})) is None


def test_clarifying_a_relative_resize_keeps_direction_and_live_value(assistant_rig):
    run, calls = assistant_rig.run, assistant_rig.records
    result = run([], message="The legend.",
        conversationState={"request":"A little bigger again, please.", "module":"qc.coverage", "workflow":"protein",
            "completed":[], "selections":[], "status":"needs_clarification"},
        view={"module":"qc.coverage", "workflow":"protein", "controls":[
            {"id":"title", "label":"Title / Size", "type":"number", "value":"14", "appearance":True, "permission":"view"},
            {"id":"legend", "label":"Legend / Text size", "type":"number", "value":"9", "appearance":True, "permission":"view"}]})
    assert not calls and len(result.actions) == 1
    assert result.actions[0].target == "legend" and result.actions[0].value == "10.8"


def test_condition_colour_is_not_a_title_colour():
    from app.schemas.assistant import UiAction, UiControl
    request = AssistantRequest(message="Colour condition B blue (#0000ff).", view={"module": "singleProtein.boxplot"})
    action = UiAction(type="set_control", target="colour", value="#0000ff")
    title = UiControl(id="colour", label="Title / Colour", type="color", value="#000000")
    condition = title.model_copy(update={"label": "Condition colors / B"})
    assert assistant._scope_problem(request, action, title)
    assert assistant._scope_problem(request, action, condition) is None


@pytest.mark.parametrize("question", ["Set the Treated condition colour to #cc3300.", "Set condition Treated to #cc3300."])
def test_condition_colour_is_a_property_not_a_condition_identifier(question):
    from app.schemas.assistant import UiAction, UiControl
    control = UiControl(id="colour", label="Names and colours / Condition colors / Treated", type="color", value="#000000", appearance=True)
    request = AssistantRequest(message=question, view={"module":"singleProtein.boxplot"})
    assert assistant._scope_problem(request, UiAction(type="set_control",target="colour",value="#cc3300"), control) is None


@pytest.mark.parametrize("question,blocked", [("Make the legend smaller and title bigger.",True),
    ("Change the legend font size to 8.",True), ("Use Times New Roman for the title.",False)])
def test_text_size_request_does_not_authorize_font_family(question, blocked):
    from app.schemas.assistant import UiAction, UiControl
    control = UiControl(id="font", label="Font / Title", type="select", value="", appearance=True,
        options=["", "times"], optionLabels={"times":"Times New Roman"}, optionCount=2)
    result = assistant._scope_problem(AssistantRequest(message=question, view={"module":"singleProtein.boxplot"}),
        UiAction(type="set_control", target="font", value="times"), control)
    assert bool(result) == blocked


def test_compound_selection_styles_without_touching_the_advanced_toggle(assistant_rig, monkeypatch):
    monkeypatch.setattr(assistant, "_resolve_chat_model", lambda *args: "synthetic")
    monkeypatch.setattr(assistant, "assistant_completion", lambda *args, **kwargs: pytest.fail("Premature planner"))
    message = "Now select phosphosite K23, not K17, and rotate the x-axis tick labels to 30 degrees."
    result = assistant.assistant_step(AssistantRequest(message=message, view=_feature_view("K17")))
    # application first; the styling follows in the next step.
    assert [(a.type, a.value) for a in result.actions] == [("set_control", "K23")]
    selected = _feature_view("K23")
    # Appearance settings are registered whether or not the user shows the panel,
    # so the next step styles the plot directly instead of flipping a toggle.
    selected["controls"].append(_control("rot", "X axis / X tick label rotation", value="0", min=-90, max=90))
    result = assistant_rig.run(['{"task":"ui","styles":[{"element":"x ticks","property":"rotation","operation":"set","value":"30"}]}'],
                               message=message, view=selected, receipts=["Set Protein / Site to K23."])
    assert [(a.type, a.target, a.value) for a in result.actions] == [("set_control", "rot", "30")]


@pytest.mark.parametrize("message", [
    "For the current boxplot, colour condition B blue (#0000ff), tilt the x-axis tick labels by 60 degrees, and hide the top border. Leave the selected site and the analysis settings unchanged.",
    "Use the minimal theme. Keep the comparison unchanged.",
    "Hide the top border; do not change the scientific settings.",
])
def test_scoped_preservation_only_advertises_appearance(assistant_rig, message):
    from app.services.assistant_routing import appearance_only_request
    assert appearance_only_request(message)
    view = _styling_view()
    for control in view["controls"]:
        control["appearance"] = True
        if control["id"] == "color":
            control["label"] = "Condition colour / B"
    view["controls"].append({"id": "test", "label": "Test", "type": "select", "value": "student", "options": ["student", "welch"]})
    view["controls"].append({"id": "site", "label": "Protein / Site", "type": "select", "value": "K0", "permission": "view"})
    view["destinations"] = {"stats.volcano": "Volcano"}
    call = assistant.plan_request(AssistantRequest(message=message, view=view))
    expected = {("frame", "top"), ("x ticks", "rotation"), ("condition:B", "color")} if "tilt" in message else {("frame", "top")}
    advertised = {(row["element"], row["property"]) for row in call.inputs["styling"]}
    assert expected <= advertised
    assert not call.control_targets
    assert "view" not in call.inputs
    assert all(row["element"] not in {"site", "test"} for row in call.inputs["styling"])
    run = assistant_rig.run
    with pytest.raises(ValueError, match="only cosmetic"):
        run([json.dumps({"task": "ui", "actions": [{"type": "set_control", "target": "test", "value": "welch"}]})], message=message, view=view)


@pytest.mark.parametrize("message,kind", [
    ("Show protein PROT11 across the canvas, comparing A and B. After the plots load, explain what they show for this protein. Do not expand it into phosphosites.", "protein"),
    ("Build the canvas for phosphosite K11. Once loaded, describe the results. Do not switch to protein data.", "phospho"),
    ("Show phosphoprotein P1 on the canvas and summarise the plots.", "phosprot"),
    ("Put protein MAPK1 on the analysis canvas and give me a short explanation.", "protein"),
])
def test_compound_canvas_uses_positive_feature_scope(assistant_rig, message, kind):
    from app.services.assistant_routing import canvas_explanation_request
    call = assistant.plan_request(AssistantRequest(message=message, view={"module": "analysis.canvas"}))
    assert call.tasks == ["canvas_focus", "clarify"]
    assert call.stated == kind and not call.all_sites_requested
    assert canvas_explanation_request(message)


def test_control_discovery_is_read_only_and_uses_displayed_option_names(assistant_rig):
    run, reads = assistant_rig.run, assistant_rig.reads
    result = run(['{"task":"plot_controls","query":"font"}'], message="Which fonts can I use here?",
                 view={"module": "singleProtein.boxplot", "controls": [
                     {"id": "font", "label": "Font / All text", "type": "select", "value": "helvetica", "permission": "view", "appearance": True,
                      "options": ["helvetica", "times"], "optionLabels": {"helvetica": "Helvetica / Arial", "times": "Times New Roman"}}]})
    assert not result.actions and not reads
    assert "Times New Roman (times)" in result.answer
    assert "Nothing was changed" in result.answer


def test_control_discovery_cannot_smuggle_a_change(assistant_rig):
    run = assistant_rig.run
    with pytest.raises(ValueError, match="evidence request"):
        run(['{"task":"plot_controls","actions":[{"type":"set_control","target":"top","value":false}]}'],
            message="What can I change here?", view=_styling_view())


def test_canvas_cannot_substitute_another_uploaded_identifier(assistant_rig, monkeypatch):
    run = assistant_rig.run
    monkeypatch.setattr(assistant, "resolve_canvas_focus", lambda *args, **kwargs: pytest.fail("Unrequested feature reached resolver"))
    result = run(['{"task":"canvas_focus","focus":{"kind":"protein","query":"PROT12"}}'],
                 message="Show protein PROT11 on the canvas. Do not use protein PROT12.", view={"module": "analysis.canvas"})
    assert result.needsClarification and not result.actions


def test_canvas_explanation_survives_model_omitting_flag(assistant_rig, monkeypatch):
    monkeypatch.setattr(assistant, "resolve_canvas_focus", lambda *args, **kwargs: {"query": "MAPK1"})
    result = assistant_rig.run(['{"task":"canvas_focus","focus":{"kind":"protein","query":"MAPK1"}}'],
        message="Put protein MAPK1 on the analysis canvas and give me a short explanation.",
        view={"module": "analysis.canvas"})
    assert result.explainAfterChanges
    assert result.actions[0].type == "focus_canvas"


def test_scoped_preservation_accepts_supported_cosmetics(assistant_rig):
    run = assistant_rig.run
    view = _styling_view()
    view['controls'][0]['appearance'] = True
    result = run(['{"task": "ui", "styles": [{"element": "frame", "property": "top", "value": false}]}'], message='Hide the top border. Leave the analysis settings unchanged.', view=view)
    assert [action.target for action in result.actions] == ['top']


def test_compact_profile_executes_an_ordinary_three_setting_request(assistant_rig):
    run, calls = assistant_rig.run, assistant_rig.calls
    edits = [{"element":"frame", "property":"top", "value":False},
             {"element":"x ticks", "property":"rotation", "value":"45"},
             {"element":"condition:A", "property":"color", "value":"red"}]
    result = run([json.dumps({"task": "ui", "styles": edits})],
                 message="Remove the top border, rotate the x tick labels to 45 and make condition A red (#ff0000).",
                 view=_styling_view())
    assert [action.target for action in result.actions] == ["top", "rot", "color"]
    assert not result.needsClarification and len(calls) == 1


def test_setter_batches_keep_a_hard_cap_and_the_request_budget(assistant_rig):
    run = assistant_rig.run
    actions = [{"element": element, "property": prop, "value": value} for element, prop, value in
               [("frame", "top", False), ("x ticks", "rotation", "45"), ("condition:A", "color", "#ff0000"), ("title", "text", "T"), ("plot", "subtitle", "S")]]
    message = "Remove the top border, rotate the labels 45 degrees, make A red, title T, subtitle S"
    result = run([json.dumps({"task": "ui", "styles": actions})], message=message, view=_styling_view())
    assert [a.target for a in result.actions] == ["top", "rot", "color", "extra"]
    result = run([json.dumps({"task": "ui", "styles": actions[:2]})], message=message, view=_styling_view(),
                 receipts=["done"] * 7)
    assert [a.target for a in result.actions] == ["top"]
    # request cleanly instead of raising; nothing from it runs.
    result = run([json.dumps({"task": "ui", "styles": actions[:2]})], message="Change these", view=_styling_view(),
                 receipts=["done"] * 8)
    assert result.stoppedEarly and not result.actions and "too many changes" in result.answer
    # Before any completed change a rejected proposal is still an error.
    with pytest.raises(ValueError, match="unavailable"):
        run([json.dumps({"task": "ui", "styles": actions})], message="Change these",
            view={**_styling_view(), "controls": _styling_view()["controls"][:1]})


def test_a_navigation_still_stands_alone(assistant_rig):
    run = assistant_rig.run
    view = {**_styling_view(), "destinations": {"qc.cv": "CV"}}
    result = run([json.dumps({"task": "ui", "actions": [{"type": "navigate", "target": "qc.cv", "value": ""},
                                                         {"type": "set_control", "target": "rot", "value": "45"}]})],
                 message="Open CV and rotate labels", view=view)
    assert [(a.type, a.target) for a in result.actions] == [("navigate", "qc.cv")]


def test_a_model_cannot_select_a_feature_the_user_did_not_name(assistant_rig):
    run = assistant_rig.run
    plan = {"task": "ui", "actions": [{"type": "set_control", "target": "site", "value": "K10"}]}
    result = run([json.dumps(plan)], message="Select the site I asked about earlier", view=_feature_view())
    assert result.needsClarification and not result.actions
    assert "did not name" in result.answer


@pytest.mark.parametrize("message,extra", [
    ("Choose phosphosite K17 and explain what this plot tells me.", {}),
    ("Keep that site selected", {"conversationState": {"request": "Choose K17", "module": "singleProtein.boxplot",
                                                        "workflow": "phosphosite", "completed": [], "status": "completed",
                                                        "selections": [{"label": "Protein / Site", "value": "K17"}]}}),
])
def test_named_or_remembered_features_are_selected(assistant_rig, message, extra):
    run = assistant_rig.run
    plan = {"task": "ui", "actions": [{"type": "set_control", "target": "site", "value": "K17"}]}
    result = run([json.dumps(plan)], message=message, view=_feature_view(), **extra)
    assert result.actions and result.actions[0].value == "K17"


def test_k1_does_not_ground_k17(assistant_rig):
    run = assistant_rig.run
    plan = {"task": "ui", "actions": [{"type": "set_control", "target": "site", "value": "K17"}]}
    result = run([json.dumps(plan)], message="Select site K1", view=_feature_view())
    assert [(a.value, result.model) for a in result.actions] == [("K1", "application")]
    view = _feature_view()
    view["controls"][0]["options"] = [f"K{i}" for i in range(10, 40)]  # K1 not an option: planner path
    result = run([json.dumps(plan)], message="Select site K1", view=view)
    assert result.needsClarification and not result.actions


@pytest.mark.parametrize("value,message,allowed", [
    ("P1;P2", "Select protein P1", False),
    ("P1;P2", "Select protein P1;P2", True),
    ("K17", "Select site K17.2", False),
    ("K17", "Select site K17.", True),
])
def test_entity_grounding_preserves_complete_identifiers(assistant_rig, value, message, allowed):
    run = assistant_rig.run
    view = _feature_view()
    view["controls"][0].update(options=["K0", value], optionCount=2)
    plan = {"task": "ui", "actions": [{"type": "set_control", "target": "site", "value": value}]}
    result = run([json.dumps(plan)], message=message, view=view)
    assert bool(result.actions) is allowed
    assert result.needsClarification is (not allowed)


def test_feature_candidates_come_from_the_data(sites):
    assert canvas_focus.feature_candidates("phospho", parent="P1") == ["K2", "K3"]
    assert canvas_focus.feature_candidates("phospho", parent="p1") == ["K2", "K3"], "case-insensitive"
    assert "K10" not in canvas_focus.feature_candidates("phospho", parent="P1"), "P1 is not P10"
    assert canvas_focus.feature_candidates("phospho", prefix="K7") == ["K7", *[f"K7{i}" for i in range(10)]]
    assert canvas_focus.feature_candidates("phospho", parent="G3") == ["K7"]


def test_parent_protein_request_lists_its_sites_without_a_model(assistant_rig, sites):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run([], message="Select the phosphosite for protein P1. If there is more than one site, ask me which one.",
                 view=_feature_view())
    assert result.needsClarification and not result.actions and not calls and not reads
    assert '"K2", "K3"' in result.answer and "K10" not in result.answer


def test_prefix_request_keeps_every_prefix_match_even_with_an_exact_one(assistant_rig, sites):
    """held-out 'ambiguous': the exact K7 hid K70-K79."""
    run, calls = assistant_rig.run, assistant_rig.calls
    result = run([], message="Find the phosphosite whose uploaded identifier starts with K7. Ask me to choose if "
                             "several match; do not pick one for me.", view=_feature_view())
    assert result.needsClarification and not result.actions and not calls
    assert "11 match" in result.answer and '"K7"' in result.answer and '"K79"' in result.answer


def test_a_single_candidate_is_selected_by_the_application(assistant_rig, sites):
    run, calls = assistant_rig.run, assistant_rig.calls
    result = run([], message="Select the phosphosite of gene G3", view=_feature_view())
    assert result.actions[0].type == "set_control" and result.actions[0].value == "K7" and not calls


@pytest.mark.parametrize("verb", ["List", "Find", "Show"])
def test_single_candidate_lookup_does_not_select(assistant_rig, sites, verb):
    run, calls = assistant_rig.run, assistant_rig.calls
    result = run([], message=f"{verb} the phosphosite of gene G3", view=_feature_view())
    assert not result.actions and not calls
    assert '"K7"' in result.answer and "No selection was changed" in result.answer


@pytest.mark.parametrize("suffix", [
    "and rotate its labels", "and change its colour", "and explain the results",
    "; hide the top border", "and then open the volcano",
])
def test_compound_feature_requests_reach_the_planner(suffix):
    request = AssistantRequest(message=f"Select the phosphosite of gene G3 {suffix}", view=_feature_view())
    assert feature_request_mode(request.message) is None
    assert assistant._feature_response(request, 1) is None


def test_old_mentions_do_not_authorize_new_feature_selection(assistant_rig):
    run = assistant_rig.run
    plan = {"task": "ui", "actions": [{"type": "set_control", "target": "site", "value": "K17"}]}
    view = _feature_view()
    view["controls"][0]["options"] = [f"K{i}" for i in range(10, 40)]  # K2 not an option: planner path
    result = run([json.dumps(plan)], message="Select site K2", view=view,
                 messages=[{"role": "user", "content": "Earlier we discussed K17"}])
    assert result.needsClarification and not result.actions


def test_semantic_styling_resolves_to_live_targets(assistant_rig):
    run, calls = assistant_rig.run, assistant_rig.calls
    plan = {"task": "ui", "styles": [{"element":"x ticks", "property":"rotation", "value":"45"}]}
    result = run([json.dumps(plan)], message="Rotate the x tick labels to 45 degrees", view=_styling_view())
    assert "control:0" not in json.dumps(calls[0])
    assert result.actions[0].target == "rot"
    assert result.actions[0].value == "45"


def test_control_alias_cannot_bypass_validation(assistant_rig):
    run = assistant_rig.run
    plan = {"task": "ui", "actions": [{"type": "set_control", "target": "control:0", "value": "false"}]}
    with pytest.raises(ValueError, match="only cosmetic"):
        run([json.dumps(plan)], message="Remove the top border", view=_styling_view())


def test_feature_requests_do_not_capture_other_intent():
    assert feature_request("Explain the site for protein P1") is None
    assert feature_request("Select phosphosite K17") is None
    assert feature_request("Show sites of protein P1") == {"parent": "P1"}


@pytest.mark.parametrize("message,expected", [
    ("I need a pair of protein boxplot tiles on this canvas. Please add them without removing anything.",
     {"type": "proteinBoxplot", "count": 2}),
    ("Could you add two ORA tiles?", {"type": "oraList", "count": 2}),
    ("Create three line plots on the canvas", {"type": "proteinLineplot", "count": 3}),
    ("Add another volcano plot, keep the existing tiles.", {"type": "volcano", "count": 1}),
])
def test_paraphrased_additions_are_typed(message, expected):
    assert canvas_add_request(message) == expected


@pytest.mark.parametrize("message", [
    "Add one protein boxplot tile and rotate its labels", "Add two volcano tiles and remove the ORA tile",
    "Add a pair of boxplots for TP53", "Why add two volcano tiles?", "Add volcano tiles",
])
def test_additions_with_other_intent_go_to_the_planner(message):
    assert canvas_add_request(message) is None


def test_free_text_feature_lists_are_grounded_per_identifier(assistant_rig):
    run = assistant_rig.run
    view = {"module": "singleProtein.lineplot", "controls": [
        {"id": "list", "label": "Proteins or genes (comma, space, or newline)", "type": "text", "value": "", "permission": "view"}]}
    plan = lambda value: json.dumps({"task": "ui", "actions": [{"type": "set_control", "target": "list", "value": value}]})
    assert run([plan("P1, P2")], message="Show P1 and P2 in the line plot", view=view).actions
    result = run([plan("P1, P7")], message="Show P1 and P2 in the line plot", view=view)
    assert result.needsClarification and not result.actions


@pytest.mark.parametrize('name,kind', [('protein boxplot', 'proteinBoxplot'), ('protein lineplot', 'proteinLineplot'),
                                     ('volcano', 'volcano'), ('control volcano', 'volcanoControl'), ('ORA', 'oraList')])
def test_explicit_canvas_addition_bypasses_model(assistant_rig, name, kind):
    run, calls = assistant_rig.run, assistant_rig.calls
    result = run([], message=f'Add two {name} tiles to this canvas.', view={'module': 'analysis.canvas', 'workflow': 'phospho'})
    assert result.actions[0].type == 'add_canvas_tiles'
    assert json.loads(result.actions[0].value) == {'type': kind, 'count': 2}
    assert calls == []


def test_canvas_addition_navigation_and_budget(assistant_rig):
    run, calls = assistant_rig.run, assistant_rig.calls
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


def test_provider_cannot_invent_internal_canvas_addition(assistant_rig):
    run = assistant_rig.run
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
def test_focus_cannot_substitute_levels_expand_sites_or_bypass_resolution(assistant_rig, message, plan):
    run = assistant_rig.run
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


@pytest.mark.parametrize("actions", [[], [{"type": "set_control", "target": "rot", "value": "45"}]])
def test_ui_clarification_never_applies_actions_or_reads_results(assistant_rig, actions):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run([json.dumps({"task": "ui", "clarification": "control",
                             "actions": actions, "explainAfterChanges": True})],
                 message="Rotate the labels and explain the plot")
    assert result.needsClarification and not result.actions and not result.explainAfterChanges
    assert result.answer == "Which plot setting should I change, and to what value?"
    assert len(calls) == 1 and not reads


def test_clarification_cannot_include_invented_site_associations(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    with pytest.raises(ValueError, match="invalid plan"):
        run(['{"task":"clarify","clarification":"P1 has K0 and K1. Which site?"}'], message="Select the site for P1")
    assert len(calls) == 1 and not reads


def test_unresolved_entity_asks_without_explanation_generation(assistant_rig):
    run, calls, evidence = assistant_rig.run, assistant_rig.calls, assistant_rig.evidence
    evidence[:] = [Evidence(tool="entity_lookup", status="unavailable", text="No unique exact identifier.")]
    result = run(['{"task":"entity_lookup","query":"P1"}', '{"source":"entity_lookup","query":"P1"}'], message="Which site belongs to P1?")
    assert result.needsClarification and "exact" in result.answer
    assert len(calls) == 2 and "selected" not in result.answer


def test_unrun_canvas_ora_does_not_invent_missing_dataset_prerequisites(assistant_rig):
    run, calls, evidence = assistant_rig.run, assistant_rig.calls, assistant_rig.evidence
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
    result = assistant.assistant_step(AssistantRequest(message="Select site K79", view={"module":"singleProtein.boxplot", "workflow":"protein", "mode":{"kind":"phospho"},
        "controls":[{"id":"site","label":"Protein / Site","type":"select","value":"K79","options":["K79"],"optionCount":1}]}))
    assert not result.actions
    assert observed[0]["view"]["workflow"] == "phosphosite"
    assert "advancedOptions" not in observed[0]["view"]  # the user's panel switch is never shown to the planner


def test_action_schema_binds_targets_values_and_standalone_transitions():
    from app.services.assistant_routing import ui_actions_schema
    schema = ui_actions_schema({"module": "analysis.canvas",
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
    assert targets == {"navigate": ["qc.cv"], "search_options": ["tile", "site"], "activate_control": ["add"]}


@pytest.mark.parametrize("kind,value,extra", [
    ("checkbox", "true", {}), ("text", True, {}), ("multiple", "A", {}),
    ("number", "nan", {}), ("number", "inf", {}), ("number", "46", {"max": 45}),
    ("number", "-1", {"min": 0}), ("color", "red", {}),
    ("select", "invented", {"options": ["A"], "optionCount": 1}),
    ("multiple", ["B"], {"options": ["A"], "optionCount": 1}),
])
def test_server_rejects_invalid_control_values_before_ui(assistant_rig, kind, value, extra):
    run, reads = assistant_rig.run, assistant_rig.reads
    with pytest.raises(ValueError, match="Invalid value"):
        run([json.dumps({"task": "ui", "actions": [{"type": "set_control", "target": "known", "value": value}]})],
            message="Set the requested plot control", view={"module": "qc.cv",
            "controls": [{"id": "known", "label": "Known", "type": kind, "value": "", **extra}]})
    assert not reads


@pytest.mark.parametrize("kind,current,value,extra", [
    ("number", "45", "45.0", {}),
    ("multiple", ["A", "B"], ["B", "A"], {"options": ["A", "B"]}),
])
def test_equivalent_control_values_are_verified_complete(assistant_rig, kind, current, value, extra):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run([json.dumps({"task": "ui", "actions": [{"type": "set_control", "target": "known", "value": value}]})],
        message="Set the requested plot control", view={"module": "qc.cv",
        "controls": [{"id": "known", "label": "Known", "type": kind, "value": current, **extra}]})
    assert not result.actions and not reads and len(calls) == 1
    assert "already in place" in result.answer


def test_conflicting_setters_in_one_batch_are_rejected(assistant_rig, monkeypatch):
    run = assistant_rig.run
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("extended", 4, 2000))
    actions = [{"type": "set_control", "target": "known", "value": value} for value in ["10", "20"]]
    with pytest.raises(ValueError, match="only once per batch"):
        run([json.dumps({"task": "ui", "actions": actions})], message="Set plot width",
            view={"module": "qc.cv", "controls": [
                {"id": "known", "label": "Width", "type": "number", "value": "0"}]})


def test_already_reached_view_transitions_finish_without_another_action(assistant_rig):
    run, calls, reads = assistant_rig.run, assistant_rig.calls, assistant_rig.reads
    result = run([json.dumps({"task": "ui", "explainAfterChanges": True,
                              "actions": [{"type": "navigate", "target": "qc.cv"}]})],
        message="Open CV and explain it", view={"module": "qc.cv"})
    assert not result.actions and result.explainAfterChanges and len(calls) == 1 and not reads


def test_generation_schema_obeys_remaining_action_budget(monkeypatch):
    monkeypatch.setattr(assistant, "_execution_profile", lambda *args: ("extended", 4, 2000))
    def complete(*args, schema):
        assert schema["properties"]["actions"]["maxItems"] == 1
        return "synthetic", '{"task":"ui","actions":[]}'
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    # The Advanced budget is 40 changes per request.
    assistant.assistant_step(AssistantRequest(message="Open CV", view={"module": "qc.cv"}, receipts=["Done"] * 39))


def test_large_selection_is_not_limited_to_the_advertised_option_window(assistant_rig):
    run = assistant_rig.run
    selected = [f"K{i}" for i in range(90)]
    result = run([json.dumps({"task": "ui", "actions": [{"type": "set_control", "target": "sites", "value": selected}]})],
        message="Select these sites", view={"module": "qc.cv", "controls": [
            {"id": "sites", "label": "Sites", "type": "multiple", "value": [], "options": selected[:40], "optionCount": 100}]})
    assert result.actions[0].value == selected
