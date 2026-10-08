"""What the visible parts of a plot are, in the words a user uses for them.

A user says "the bars", "the boxes" or "the points"; the controls say
"Condition colors / A". Without this link a request such as "change the bar
colour to black" names no condition, and the scope check (rightly) refused to
recolour conditions nobody named (2026-10-07, glm5 on the coverage plot: the
model's plan was correct, the application turned it down).

The link is per plot: on the coverage plot each bar is a sample filled with
its condition's colour, so "the bars" names every condition shown. Plots whose
marks are not coloured by condition are not listed, and then the words do not
widen any scope.
"""
from __future__ import annotations

import re

from app.schemas.assistant import AssistantRequest

# module -> (what the marks are called, words a user uses, what they show)
MARKS: dict[str, tuple[str, str, str]] = {
    "qc.coverage": ("bars", r"bars?|columns?", "one bar per sample, filled with its condition's colour"),
    "completeness.missingPlot": ("bars", r"bars?|columns?", "bars filled with each condition's colour"),
    "qc.boxplot": ("boxes", r"box(?:es)?|boxplots?|violins?", "one box per sample, filled with its condition's colour"),
    "qc.cv": ("boxes", r"box(?:es)?|boxplots?|violins?", "one distribution per condition, in its condition's colour"),
    "qc.histogram": ("distributions", r"bars?|histograms?|lines?|curves?|distributions?",
                     "intensity distributions in each condition's colour"),
    "qc.abundance": ("curves", r"lines?|curves?|points?|dots?", "rank curves in each condition's colour"),
    "qc.pca": ("points", r"points?|dots?|markers?", "one point per sample, in its condition's colour"),
    "singleProtein.boxplot": ("boxes", r"box(?:es)?|boxplots?|points?|dots?", "one box per condition, in its colour"),
    "singleProtein.lineplot": ("lines", r"lines?|points?|dots?|markers?", "values per sample, in each condition's colour"),
}
_PALETTE_WORDS = re.compile(r"\b(?:colou?r\s*(?:scheme|palette|scheme)s?|palettes?|all\s+(?:the\s+)?colou?rs|"
                            r"data\s+colou?rs|condition\s+colou?rs|group\s+colou?rs)\b", re.I)
_CONDITION_COLOUR = re.compile(r"Condition colou?rs? / (.+)$", re.I)


def condition_colours(request: AssistantRequest) -> dict[str, str]:
    """Condition name -> its colour override, "" while the plot's own palette applies.

    Each condition has a colour picker and a text field. The text field holds
    the override; the picker shows a placeholder grey (#64748b) while there is
    none, which is not the colour drawn (2026-10-07: the bars were the default
    blue and orange while the picker read grey)."""
    pickers: dict[str, str] = {}
    texts: dict[str, str] = {}
    for control in request.view.controls:
        match = _CONDITION_COLOUR.search(control.label)
        if match and control.appearance and isinstance(control.value, str):
            if control.type == "text":
                texts[match[1]] = control.value.strip()
            elif control.type == "color":
                pickers[match[1]] = control.value
    return {name: texts.get(name, pickers.get(name, "")) for name in [*pickers, *[n for n in texts if n not in pickers]]}


def _marks(request: AssistantRequest) -> tuple[str, str, str] | None:
    module = request.view.module
    if module in MARKS:
        return MARKS[module]
    return None


def names_all_conditions(request: AssistantRequest, message: str | None = None) -> bool:
    """The request names the plot's condition-coloured marks (or its palette) as a whole."""
    text = request.message if message is None else message
    if not condition_colours(request):
        return False
    if _PALETTE_WORDS.search(text):
        return True
    marks = _marks(request)
    return bool(marks and re.search(r"\b(?:" + marks[1] + r")\b", text, re.I))


def describe(request: AssistantRequest) -> list[str]:
    """Short lines for the planner: what each visible part is and its colour now."""
    from app.services.assistant_styling import style_controls

    lines = []
    colours = condition_colours(request)
    marks = _marks(request)
    if marks and colours:
        current = ", ".join(f"{name} {value or 'the default palette colour'}" for name, value in colours.items())
        lines.append(f"{marks[0]}: {marks[2]} (elements condition:<name> / color; now {current}). "
                     f"Recolouring the {marks[0]} means setting every condition's colour.")
    elif colours:
        lines.append("condition colours (elements condition:<name> / color): " +
                     ", ".join(f"{name} {value or 'the default palette colour'}" for name, value in colours.items()))
    seen = set()
    for (element, prop), control in style_controls(request).items():
        if prop == "color" and not element.startswith(("condition:", "sample:")) and element not in seen:
            seen.add(element)
            lines.append(f"{element}: colour {control.value or 'default'}")
    return lines[:14]
