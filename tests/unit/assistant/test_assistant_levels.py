"""Assistant levels: what each model may do, and the tools Advanced models get.

2026-10-07, glm5 on a llama.cpp server: rated "unknown / Low", it was given
the smallest toolbox, its correct plan for "change the bar color from red to
black" was refused (the request named no condition), a restyle ran out of its
1,024-token reply budget while thinking, and a Nature request was declined by
rule. These tests hold the corrections; the rules themselves are unchanged.
"""
import json

import pytest

from app.schemas.assistant import AssistantRequest, Evidence
from app.services import assistant_plot_parts, assistant_presets, assistant_prose
from app.services import scientific_assistant as assistant

GREY, RED = "#64748b", "#ff0000"


def _coverage_view(colour=GREY):
    def control(id_, label, type_, value, **extra):
        return {"id": id_, "label": label, "type": type_, "value": value, "appearance": True, "permission": "view", **extra}
    return {"module": "qc.coverage", "destinations": {"qc.coverage": "QC Pipeline / Coverage Plot"}, "controls": [
        control("ca", "Names and colours / Condition colors / A", "color", colour),
        control("cb", "Names and colours / Condition colors / B", "color", colour),
        control("ref", "Reference line / Colour", "color", RED),
        control("font", "Font / All text", "select", "", options=["", "helvetica", "times"]),
        control("title", "Title / Size", "number", "12"),
        control("xt", "X axis / X tick label size", "number", "10"),
        control("legend", "Legend / Text size", "number", "10"),
        control("w", "Width (cm)", "number", "20", min=1, max=60),
        control("h", "Height (cm)", "number", "10", min=1, max=60),
        control("dpi", "DPI", "number", "300", min=72, max=600),
        control("grid", "Frame and grid / Grid lines / Show", "checkbox", True),
        control("frame", "Frame and grid / Axis frame / Width", "number", "0.8", min=0),
        control("theme", "Background / Theme", "select", "default", options=["default", "white"]),
    ]}


def _targets(result):
    return {action.target: action.value for action in result.actions}


@pytest.fixture
def advanced(assistant_rig):
    assistant_rig.profile["value"] = ("extended", 6, 2000)
    return assistant_rig


def test_the_bars_are_the_condition_colours(assistant_rig):
    request = AssistantRequest(message="make the bars black", view=_coverage_view())
    assert assistant_plot_parts.names_all_conditions(request)
    assert "bars" in assistant_plot_parts.describe(request)[0]
    result = assistant_rig.run([], message="change the bar color to black", view=_coverage_view())
    assert _targets(result) == {"ca": "#000000", "cb": "#000000"} and assistant_rig.calls == []


def test_a_models_plan_for_the_bars_is_no_longer_refused(assistant_rig):
    # The bars are grey and the reference line is red, so the application does
    # not shortcut "from red"; the model's own plan for the bars is accepted.
    plan = {"task": "ui", "styles": [{"element": "condition:A", "property": "color", "value": "#000000"},
                                     {"element": "condition:B", "property": "color", "value": "#000000"}]}
    result = assistant_rig.run([json.dumps(plan)], message="change the bar color from red to black", view=_coverage_view())
    assert _targets(result) == {"ca": "#000000", "cb": "#000000"} and not result.needsClarification
    assert any("bars" in line for line in assistant_rig.calls[0]["plotParts"])


def test_basic_models_get_journal_styles_from_the_application(assistant_rig):
    result = assistant_rig.run([], message="Please make this plot fit the Nature style", view=_coverage_view())
    changes = _targets(result)
    assert assistant_rig.calls == []
    assert changes["font"] == "helvetica" and changes["title"] == "7" and changes["xt"] == "6"
    assert changes["w"] == "8.9" and changes["h"] == "4.5" and changes["grid"] is False
    assert changes["ca"] in assistant_presets.OKABE_ITO and changes["ca"] != changes["cb"]
    assert assistant_presets.PRESETS["nature"].source in result.answer
    assert result.actionBudget >= len(result.actions) > 8


def test_an_unchecked_journal_is_named_as_such(assistant_rig):
    result = assistant_rig.run([], message="Make it look like a Science paper", view=_coverage_view())
    assert result.needsClarification and "checked figure specification for Science" in result.answer
    assert not result.actions and assistant_rig.calls == []


def test_basic_models_improve_a_plot_with_the_publication_style(assistant_rig):
    result = assistant_rig.run([], message="Please make the plot look more professional", view=_coverage_view())
    assert _targets(result)["font"] == "helvetica" and "suggestion" in result.answer and assistant_rig.calls == []


def test_advanced_models_use_presets_and_their_own_edits(advanced):
    plan = {"task": "ui", "preset": "cell", "styles": [{"element": "title", "property": "size", "value": "9"}],
            "designNote": "Cell Press asks for 6-8 pt text; I kept the title at 9 pt so it stands out."}
    result = advanced.run([json.dumps(plan)], message="Format this for a Cell paper and keep the title a bit larger",
                          view=_coverage_view())
    changes = _targets(result)
    assert changes["title"] == "9" and changes["w"] == "8.5" and changes["frame"] == "0.75"
    assert assistant_presets.PRESETS["cell"].source in result.answer
    record = advanced.records[0]
    assert "presets" in record["data"] and record["schema"]["properties"]["preset"]["enum"][1:] == list(assistant_presets.PRESETS)
    assert "Never invent journal requirements" not in record["instruction"]


def test_advanced_free_design_keeps_colours_colour_blind_safe(advanced):
    plan = {"task": "ui", "styles": [
        {"element": "all text", "property": "font family", "value": "helvetica"},
        {"element": "condition:A", "property": "color", "value": "#123456"},
        {"element": "condition:B", "property": "color", "value": "#d55e00"},
        {"element": "frame", "property": "width", "value": "0.5"}],
        "designNote": "A single sans-serif font and a 0.5 frame keep the bars in focus. Titles are now 12 pt."}
    result = advanced.run([json.dumps(plan)], message="please upgrade the plot to what you think looks best",
                          view=_coverage_view())
    changes = _targets(result)
    assert "ca" not in changes and changes["cb"] == "#d55e00" and changes["frame"] == "0.5"
    assert "colour-blind-safe" in result.answer and "0.5 frame" in result.answer and not result.explainAfterChanges
    # A sentence claiming a value nothing set is dropped from the design note.
    assert "12 pt" not in result.answer
    # Free design does not resize the figure unless asked.
    assert "w" not in changes


def test_advanced_lookups_run_before_the_plan(advanced):
    lookup = {"task": "lookup", "lookups": [{"tool": "preset", "query": "nature"}]}
    plan = {"task": "ui", "preset": "nature"}
    result = advanced.run([json.dumps(lookup), json.dumps(plan)], message="Make it Nature style", view=_coverage_view())
    assert len(advanced.calls) == 2 and advanced.calls[1]["lookupResults"][0]["tool"] == "preset"
    assert "lookup" in advanced.records[0]["schema"]["properties"]["task"]["enum"]
    assert _targets(result)["w"] == "8.9"


def test_an_unresolvable_advanced_plan_comes_back_once_with_the_problem(advanced):
    wrong = {"task": "ui", "styles": [{"element": "title", "property": "size", "value": "huge"}]}
    right = {"task": "ui", "styles": [{"element": "title", "property": "size", "value": "14"}]}
    result = advanced.run([json.dumps(wrong), json.dumps(right)], message="make the title 14", view=_coverage_view())
    assert "problem" in json.dumps(advanced.calls[1]["lookupResults"]) and _targets(result) == {"title": "14"}


def test_basic_models_get_no_lookups_or_presets(assistant_rig):
    plan = {"task": "ui", "styles": [{"element": "title", "property": "size", "value": "14"}]}
    assistant_rig.run([json.dumps(plan)], message="make the title 14 and bold", view=_coverage_view())
    record = assistant_rig.records[0]
    assert "lookup" not in record["schema"]["properties"]["task"]["enum"]
    assert record["schema"]["properties"]["preset"]["enum"] == [""] and "presets" not in record["data"]


@pytest.mark.parametrize("message", ["hello", "Hi there!", "what can you do?", "thanks!"])
def test_greetings_get_a_human_answer_without_a_model(assistant_rig, message):
    result = assistant_rig.run([], message=message, view=_coverage_view())
    assert assistant_rig.calls == [] and not result.needsClarification and not result.actions
    assert "Which plot or selection" not in result.answer


def test_advanced_models_write_their_answer_and_unconfirmed_sentences_go(advanced):
    advanced.evidence = [Evidence(tool="qc.coverage", status="available",
                                  text="coverage_answer_summary|samples=12|groups=4|median_proteins=4102.5")]
    answer = {"answer": "You see 12 samples in 4 groups. The median sample has about 4103 proteins. "
                        "MAPK1 is the most detected protein with 9999 hits."}
    replies = ['{"task":"current_plot"}', '{"source":"result:qc.coverage","query":""}', json.dumps(answer)]
    result = advanced.run(replies, message="What does this plot show?", view=_coverage_view())
    assert "12 samples in 4 groups" in result.answer and "4103" in result.answer
    assert "MAPK1" not in result.answer and "left out 1 sentence" in result.answer


def test_prose_check_rounding_signs_and_percentages():
    evidence = ["volcano|log2fc=-1.05|p=0.0123|fraction_up=0.125"]
    checked, removed = assistant_prose.verify(
        "The change is 1.05 lower. p is 0.012. 12.5% are up. The sign is +1.05.", evidence, "")
    assert removed == 1 and "+1.05" not in checked and "12.5%" in checked


def test_the_plot_image_goes_only_to_advanced_models(advanced, monkeypatch):
    seen = []
    def complete(request, instruction, data, **kwargs):
        seen.append(kwargs.get("image"))
        return "synthetic", json.dumps({"task": "ui", "styles": [{"element": "title", "property": "size", "value": "14"}]})
    monkeypatch.setattr(assistant, "assistant_completion", complete)
    image = "data:image/png;base64,iVBORw0KGgo="
    assistant.assistant_step(AssistantRequest(message="make the title 14", view=_coverage_view(), plotImage=image))
    assert seen == [image]
    advanced.profile["value"] = ("compact", 2, 600)
    assistant.assistant_step(AssistantRequest(message="make the title 15", view=_coverage_view(), plotImage=image))
    assert seen[-1] is None


def test_the_budget_follows_the_level(advanced):
    plan = {"task": "ui", "styles": [{"element": "title", "property": "size", "value": "14"}]}
    assert advanced.run([json.dumps(plan)], message="make the title 14", view=_coverage_view()).actionBudget == 40
    advanced.profile["value"] = ("compact", 2, 600)
    assert advanced.run([json.dumps(plan)], message="make the title 14", view=_coverage_view()).actionBudget == 8


@pytest.mark.parametrize("message", ["Is this ready for publication?", "How could I make this look more professional?",
                                     "What is the nature of these bars?"])
def test_a_question_about_style_changes_nothing_by_itself(assistant_rig, message):
    reply = json.dumps({"task": "clarify", "clarification": "request"})
    result = assistant_rig.run([reply, reply, reply], message=message, view=_coverage_view())
    assert not result.actions


def test_keeping_everything_else_does_not_hand_over_the_whole_look(assistant_rig):
    plan = {"task": "ui", "styles": [{"element": "reference line", "property": "color", "value": "#404040"},
                                     {"element": "all text", "property": "font family", "value": "times"}]}
    result = assistant_rig.run([json.dumps(plan)], message="make the dashed line dark grey, keep everything else",
                               view=_coverage_view())
    assert _targets(result) == {"ref": "#404040"} and "font" in result.answer.lower()


def test_the_axis_labels_are_both_axes_labels(assistant_rig):
    view = _coverage_view()
    view["controls"] += [
        {"id": "xl", "label": "X axis / Axis label / Size", "type": "number", "value": "10", "appearance": True, "permission": "view"},
        {"id": "yl", "label": "Y axis / Axis label / Size", "type": "number", "value": "10", "appearance": True, "permission": "view"},
        {"id": "tb", "label": "Title / Bold", "type": "checkbox", "value": False, "appearance": True, "permission": "view"}]
    plan = {"task": "ui", "styles": [{"element": "title", "property": "bold", "value": True},
                                     {"element": "x label", "property": "size", "operation": "increase", "value": ""},
                                     {"element": "y label", "property": "size", "operation": "increase", "value": ""}]}
    result = assistant_rig.run([json.dumps(plan)], message="make the title bold and the axis labels a bit bigger", view=view)
    assert _targets(result) == {"tb": True, "xl": "12", "yl": "12"}


def test_an_unset_condition_colour_is_the_palette_not_the_pickers_placeholder():
    view = _coverage_view()
    view["controls"].append({"id": "ta", "label": "Names and colours / Condition colors / A", "type": "text", "value": "",
                             "appearance": True, "permission": "view"})
    request = AssistantRequest(message="make the bars black", view=view)
    assert assistant_plot_parts.condition_colours(request)["A"] == ""
    assert "A the default palette colour" in assistant_plot_parts.describe(request)[0]
