import pytest

from app.schemas.assistant import AssistantRequest, StyleEdit
from app.services import assistant_styling as styling
from assistant_support import _control


def request(*controls, message="Change the plot style", **fields):
    return AssistantRequest(message=message, view={"module": "singleProtein.boxplot", "controls": list(controls)}, **fields)


def edit(element="legend", property="size", **fields):
    return StyleEdit(element=element, property=property, **fields)


@pytest.mark.parametrize("label,type_,expected", [
    ("Legend / Text size", "number", ("legend", "size")),
    ("X axis / Axis label / Text", "text", ("x label", "text")),
    ("X axis / X tick label rotation", "number", ("x ticks", "rotation")),
    ("Title", "text", ("title", "text")),
    ("Title", "number", ("title", "size")),
    ("Frame and grid / Axis frame / Top", "checkbox", ("frame", "top")),
    ("Condition colors / Treated", "color", ("condition:Treated", "color")),
    ("Sample names / A", "text", ("sample:A", "label")),
    ("Tile 2: Boxplot / Title / Size", "number", ("tile 2 / title", "size")),
])
def test_live_control_semantics(label, type_, expected):
    assert styling.identity(request(_control("id", label, type_)).view.controls[0]) == expected


def test_relative_change_uses_current_value_bounds_and_receipts():
    control = _control("live-id", "Legend / Text size", value="10", min=9)
    req = request(control)
    changes = styling.resolve(req, [edit(operation="decrease")])
    assert [(a.target, float(a.value)) for a in changes] == [("live-id", 9)]
    req.receipts = ['Set Legend / Text size to "9".']
    assert styling.resolve(req, [edit(operation="decrease")]) == []
    assert styling.catalogue(req) == []


def test_relative_offsets_can_cross_zero_without_inventing_a_bound():
    req = request(_control("offset", "Legend / X offset", value="0"))
    assert float(styling.resolve(req, [edit(property="x offset", operation="decrease")])[0].value) == -1


def test_unset_optional_size_accepts_an_explicit_value_but_not_a_relative_guess():
    req = request(_control("legend", "Legend / Text size", value=""))
    assert styling.resolve(req, [edit(value="12")])[0].value == "12"
    with pytest.raises(ValueError, match="numeric"):
        styling.resolve(req, [edit(operation="increase")])


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "91", True])
def test_invalid_numeric_styles_are_rejected(value):
    req = request(_control("rot", "X tick label rotation", min=-90, max=90))
    with pytest.raises(ValueError):
        styling.resolve(req, [edit("x ticks", "rotation", value=value)])


def test_ambiguous_pairs_are_unavailable_but_duplicate_colour_inputs_are_one_setting():
    req = request(_control("one", "Title", "text"), _control("two", "Title", "text"),
                  _control("picker", "Condition colors / A", "color"),
                  _control("hex", "Condition colors / A", "text"))
    assert list(styling.style_controls(req)) == [("condition:A", "color")]
    assert styling.resolve(req, [edit("condition:A", "color", value="red")])[0].target == "picker"
    with pytest.raises(ValueError, match="ambiguous"):
        styling.resolve(req, [edit("title", "text", value="Changed")])


def test_semantic_mapping_never_exposes_scientific_or_confirmation_controls():
    req = request(_control("test", "Test type", "select"),
                  _control("size", "Legend / Text size", permission="confirm"))
    assert styling.catalogue(req) == []
    with pytest.raises(ValueError):
        styling.resolve(req, [edit(value="9")])


def test_compound_catalogue_keeps_dimensions_alongside_named_elements():
    req = request(_control("legend", "Legend / Text size"), _control("dpi", "DPI"),
                  message="Make the legend smaller and use 600 DPI")
    assert {row["element"] for row in styling.catalogue(req)} == {"legend", "plot"}


def test_compound_style_scope_accepts_explicit_dpi(assistant_rig):
    result = assistant_rig.run(['{"task":"ui","explainAfterChanges":true,"styles":[{"element":"plot","property":"dpi","value":"150"}]}'],
        message="Make the x-axis labels smaller and use 150 DPI. Leave the data alone.",
        view={"module":"singleProtein.boxplot",
              "controls":[_control("dpi", "DPI", value="300", min=72, max=600)]})
    assert result.actions[0].target == "dpi" and result.actions[0].value == "150"
    assert not result.explainAfterChanges


def test_preserving_data_does_not_forbid_explicit_cosmetics():
    from app.services.assistant_routing import planner_tasks, appearance_only_request, contradictory_preservation
    question = "Make the x-axis labels smaller, use 150 DPI and rename the title to MAPK1 overview. Leave the data alone."
    assert appearance_only_request(question)
    assert planner_tasks(question) == ["ui", "clarify"]
    assert "ui" not in planner_tasks("Leave the data alone. Impute missing values.")
    assert contradictory_preservation("Now make only the legend smaller. Keep all selections unchanged.") is None
    assert contradictory_preservation("Make the legend smaller. Keep everything unchanged.")


def test_repeated_pairs_are_rejected_and_unknown_pairs_do_not_partially_apply():
    req = request(_control("legend", "Legend / Text size", value="10"))
    with pytest.raises(ValueError, match="once"):
        styling.resolve(req, [edit(value="8"), edit(value="7")])
    with pytest.raises(ValueError, match="unavailable"):
        styling.resolve(req, [edit(value="8"), edit("unknown", value="7")])


def test_plot_rename_cannot_change_axis_label_instead():
    req = request(_control("axis", "X axis / Axis label / Text", "text"),
                  message='Call the plot "MAPK1 comparison"')
    with pytest.raises(ValueError, match="title"):
        styling.resolve(req, [edit("x label", "text", value="MAPK1 comparison")])


def test_read_only_schema_and_execution_reject_semantic_edits(assistant_rig):
    with pytest.raises(ValueError, match="does not authorize"):
        assistant_rig.run(['{"task":"ui","styles":[{"element":"legend","property":"size","value":"8"}]}'],
                          message="Explain this plot without changing anything.",
                          view={"module": "singleProtein.boxplot", "controls": [_control("legend", "Legend / Text size")]})
    assert assistant_rig.records[0]["schema"]["properties"]["styles"]["maxItems"] == 0
