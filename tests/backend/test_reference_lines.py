"""The lines drawn over the data, rather than from it.

A coverage plot's total, a volcano's thresholds, a Q-Q fit, an identity line, a
regression fit, the imputation draw area: each of these used to hardcode its own
colour, dash and width, and two of them read a colour from the advanced panel
while their interactive twins ignored it -- so the same figure changed
appearance when the renderer changed. They all come through
`resolve_reference_line` now, and this is what holds them there.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.services.plot_styling import (
    ReferenceLine,
    resolve_reference_line,
)

SERVICES = Path(__file__).resolve().parents[2] / "backend" / "app" / "services"

# Every module that draws a line over its data.
LINE_MODULES = [
    "plot_styling.py",
    "plot_images.py",
    "stats_tools.py",
    "phospho_tools.py",
    "peptide_tools.py",
    "comparison_tools.py",
]


def test_nothing_set_means_the_plot_keeps_its_own_look() -> None:
    line = resolve_reference_line({}, color="#9ca3af", style="dashed", width=0.8)
    assert line == ReferenceLine(visible=True, color="#9ca3af", style="dashed", width=0.8)


def test_the_panel_overrides_each_part_on_its_own() -> None:
    settings = {
        "referenceLineColor": "#112233",
        "referenceLineStyle": "dotted",
        "referenceLineWidth": 3,
    }
    line = resolve_reference_line(settings, color="red")
    assert (line.color, line.style, line.width) == ("#112233", "dotted", 3.0)
    assert line.visible is True


def test_the_line_can_be_switched_off() -> None:
    assert resolve_reference_line({"referenceLineVisible": False}).visible is False
    assert resolve_reference_line({"referenceLineVisible": True}).visible is True


def test_a_style_that_is_not_offered_falls_back_to_the_plot_s_own() -> None:
    line = resolve_reference_line({"referenceLineStyle": "squiggly"}, style="solid")
    assert line.style == "solid"


def test_a_negative_width_is_floored_rather_than_drawn() -> None:
    assert resolve_reference_line({"referenceLineWidth": -4}).width == 0.0


@pytest.mark.parametrize(
    ("style", "mpl", "plotly"),
    [
        ("solid", "-", "solid"),
        ("dashed", "--", "dash"),
        ("dotted", ":", "dot"),
        ("dashdot", "-.", "dashdot"),
    ],
)
def test_one_style_means_the_same_line_in_both_renderers(style: str, mpl: str, plotly: str) -> None:
    line = resolve_reference_line({"referenceLineStyle": style})
    assert line.matplotlib()["linestyle"] == mpl
    assert line.plotly()["dash"] == plotly


def test_both_renderers_are_given_the_same_colour_and_width() -> None:
    line = resolve_reference_line({"referenceLineColor": "#abcdef", "referenceLineWidth": 2})
    assert line.matplotlib()["color"] == line.plotly()["color"] == "#abcdef"
    assert line.matplotlib()["linewidth"] == line.plotly()["width"] == 2.0


def test_no_renderer_reads_the_colour_behind_the_resolver_s_back() -> None:
    """The old spelling, `advanced_text(advanced, "referenceLineColor")`, read
    the colour and nothing else -- which is how a line ended up honouring a
    colour setting while ignoring the switch beside it."""
    for name in LINE_MODULES:
        source = (SERVICES / name).read_text(encoding="utf-8")
        # `plot_styling.py` is where the resolver lives, so it reads the key
        # exactly once, inside it.
        expected = 1 if name == "plot_styling.py" else 0
        assert source.count('"referenceLineColor"') == expected, (
            f"{name} reads referenceLineColor directly; it should call "
            "resolve_reference_line so the visibility, style and width settings "
            "reach it too"
        )
    resolver = (SERVICES / "plot_styling.py").read_text(encoding="utf-8")
    body = resolver[resolver.index("def resolve_reference_line") :]
    assert '"referenceLineColor"' in body[: body.index("\ndef ", 1)]


def test_every_module_that_draws_a_guide_line_imports_the_resolver() -> None:
    for name in LINE_MODULES:
        source = (SERVICES / name).read_text(encoding="utf-8")
        assert "resolve_reference_line" in source, name


DRAWING_CALLS = {"axhline", "axvline", "add_hline", "add_vline", "hlines", "vlines"}


def _line_calls(tree: ast.AST) -> list[ast.Call]:
    """Every call in this tree that puts a straight line on a figure.

    Takes the tree rather than the source, so a caller can walk back up to the
    `if` that guards a call it finds here.
    """
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in DRAWING_CALLS
    ]


def test_no_guide_line_is_drawn_in_a_hardcoded_colour() -> None:
    """A literal colour on one of these calls is a line the panel cannot reach.

    Checked structurally rather than by grepping for `"red"`, so a line added in
    a new plot next year is caught by the same rule.
    """
    offenders: list[str] = []
    for name in LINE_MODULES:
        source = (SERVICES / name).read_text(encoding="utf-8")
        for call in _line_calls(ast.parse(source)):
            for keyword in call.keywords:
                if keyword.arg in {"color", "colors", "line_color"} and isinstance(
                    keyword.value, ast.Constant
                ):
                    offenders.append(f"{name}:{call.lineno} {keyword.arg}={keyword.value.value!r}")
    assert not offenders, "guide lines with a colour the advanced panel cannot change: " + ", ".join(
        offenders
    )


def test_every_guide_line_is_drawn_behind_the_visibility_switch() -> None:
    """A line whose colour follows the panel but which is drawn anyway is the
    half-wired state this whole change is about. Checked at every call site by
    walking up from the drawing call to an enclosing `if ....visible`.
    """
    unguarded: list[str] = []
    for name in LINE_MODULES:
        tree = ast.parse((SERVICES / name).read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for call in _line_calls(tree):
            guarded = False
            node: ast.AST | None = call
            while node is not None and not isinstance(node, ast.FunctionDef):
                parent = parents.get(node)
                if isinstance(parent, ast.If) and "visible" in ast.unparse(parent.test):
                    guarded = True
                    break
                node = parent
            if not guarded:
                unguarded.append(f"{name}:{call.lineno} {call.func.attr}")
    assert not unguarded, (
        "guide lines drawn without checking the reference-line switch: " + ", ".join(unguarded)
    )
