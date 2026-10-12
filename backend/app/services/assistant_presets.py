"""Journal and publication styles the application applies, with their sources.

Only specifications read from the journal's own guide are listed as a
journal's requirements. Everything else a preset changes is marked as a
suggestion, so the answer never presents taste as a journal rule. Journals
without a checked guide are not offered by name: the assistant says so and
offers the general publication style.

Sources (read 2026-10-07):
* Nature: research-figure-guide.nature.com/figures/preparing-figures-our-specifications
  and nature.com/documents/nature-final-artwork.pdf -- sans-serif (Helvetica or
  Arial), text 5-7 pt, panel labels 8 pt bold, 89 mm (1 column), 120/136 mm
  (1.5 columns), 183 mm (2 columns), no background gridlines, an accessible
  colour palette (citing Wong, Nat. Methods 2011), images at least 300 dpi.
* Cell Press: cell.com/figureguidelines -- Arial, text about 6-8 pt, 85 mm
  (1 column), 114 mm (1.5 columns), 174 mm (full width), line weights
  0.5-1.5 pt, colour figures 300 dpi.
* Colour-blind-safe palette: Okabe & Ito (2008), as recommended in Wong, B.
  "Points of view: Color blindness", Nat. Methods 8, 441 (2011).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas.assistant import AssistantRequest, StyleEdit

OKABE_ITO = ["#0072b2", "#d55e00", "#009e73", "#cc79a7", "#e69f00", "#56b4e9", "#f0e442", "#000000"]
TOL_BRIGHT = ["#4477aa", "#ee6677", "#228833", "#ccbb44", "#66ccee", "#aa3377", "#bbbbbb"]
TOL_MUTED = ["#332288", "#88ccee", "#44aa99", "#117733", "#999933", "#ddcc77", "#cc6677", "#882255", "#aa4499"]
GREYS = ["#000000", "#404040", "#737373", "#a6a6a6", "#d9d9d9", "#ffffff"]
PALETTES = {"okabe-ito": OKABE_ITO, "tol-bright": TOL_BRIGHT, "tol-muted": TOL_MUTED, "greys": GREYS}
SAFE_COLOURS = {colour for palette in PALETTES.values() for colour in palette}


@dataclass(frozen=True)
class Preset:
    label: str
    source: str
    widths_cm: dict[str, float]
    font: str
    sizes: dict[str, float]           # element -> pt
    stated: list[str]                 # the journal's own requirements applied
    not_settable: list[str] = field(default_factory=list)
    frame_width: float | None = None
    grid_off: bool = False
    palette: bool = False
    min_dpi: int = 300
    suggestions: dict[str, object] = field(default_factory=dict)  # (element|property) -> value


_TEXT = ("title", "x label", "y label")
_SMALL = ("x ticks", "y ticks", "legend")

PRESETS: dict[str, Preset] = {
    "nature": Preset(
        label="Nature",
        source="Nature Research figure guide (research-figure-guide.nature.com) and final artwork guide (nature.com/documents/nature-final-artwork.pdf)",
        widths_cm={"single": 8.9, "1.5": 12.0, "double": 18.3},
        font="helvetica",
        sizes={**{name: 7 for name in _TEXT}, **{name: 6 for name in _SMALL}, "value labels": 6},
        stated=["sans-serif text (Helvetica/Arial)", "text 5-7 pt", "column width", "no background gridlines",
                "an accessible colour palette", "at least 300 dpi"],
        not_settable=["panel labels (8 pt bold a, b, c) are added when the figure is assembled"],
        grid_off=True, palette=True,
    ),
    "cell": Preset(
        label="Cell Press",
        source="Cell Press figure guidelines (cell.com/figureguidelines)",
        widths_cm={"single": 8.5, "1.5": 11.4, "double": 17.4},
        font="helvetica",
        sizes={**{name: 8 for name in _TEXT}, **{name: 7 for name in _SMALL}, "value labels": 7},
        stated=["Arial-style sans-serif text (Helvetica is the closest font here)", "text 6-8 pt", "column width",
                "line weights 0.5-1.5 pt", "300 dpi for colour figures"],
        frame_width=0.75,
    ),
    "publication": Preset(
        label="general publication style",
        source="CoPYlot's general publication style, a suggestion rather than any journal's requirement; "
               "palette after Wong, Nat. Methods 8, 441 (2011)",
        widths_cm={"single": 8.8, "1.5": 12.0, "double": 18.0},
        font="helvetica",
        sizes={"title": 9, "x label": 8, "y label": 8, "x ticks": 7, "y ticks": 7, "legend": 7, "value labels": 7},
        stated=[],
        frame_width=0.8, grid_off=True, palette=True,
        suggestions={"frame|top": False, "frame|right": False, "background|theme": "white"},
    ),
}
_NAMES = {"nature": r"\bnature\b(?!\s+of\b)", "cell": r"\bcell(?:\s+press)?\b(?=.*\b(?:style|format|journal|figure|guideline|paper|publication|submission)s?\b)"}
_OTHER_JOURNALS = re.compile(r"\b(science(?:\s+magazine)?|pnas|plos(?:\s+one)?|elife|acs|jacs|embo|lancet|nejm|jbc|"
                             r"mol(?:ecular)?\s+cell(?:ular)?\s+proteomics|mcp|journal of proteome research|jpr|"
                             r"bioinformatics|nucleic acids research|nar)\b", re.I)
_PUBLICATION = re.compile(r"\b(?:publication|publish\w*|journal|paper|manuscript|submission)\b", re.I)
_STYLE = re.compile(r"\b(?:style|styled|format\w*|look|guidelines?|ready|standards?|figure|fit|match|like)\b", re.I)
_IMPROVE = re.compile(r"\b(?:look\s+(?:better|nicer|best|good|great|professional)|nicer|prettier|more\s+professional|"
                      r"upgrade|improve|polish|beautif\w*|what\s+you\s+think\s+is\s+best|best\s+(?:style|look)|"
                      # "make it look cleaner for my lab meeting" (2026-10-08): the whole look is handed over
                      r"clean(?:er)?\s*(?:up|look\w*)?|tid(?:y|ier)(?:\s+up)?|declutter\w*|less\s+cluttered|sleek\w*|"
                      r"(?:presentation|publication|slide|poster|talk)[- ]ready|"
                      r"for\s+(?:my|a|the|our)\s+(?:(?:lab|group|team)\s+meeting|talk|presentation|slides?|poster|seminar|"
                      r"defen[cs]e|lecture|report|thesis)|"
                      r"sch(?:ö|oe)ner|h(?:ü|ue)bscher|aufr(?:ä|ae)umen|aufger(?:ä|ae)umt\w*|professioneller)\b", re.I)


def requested(message: str) -> tuple[str | None, str | None]:
    """(preset key, unchecked journal name) named by a styling request."""
    text = message.lower()
    if not _STYLE.search(text) and not _PUBLICATION.search(text):
        return None, None
    for key, pattern in _NAMES.items():
        if re.search(pattern, text, re.I):
            return key, None
    other = _OTHER_JOURNALS.search(message)
    if other:
        return None, other[1]
    if _PUBLICATION.search(text) and _STYLE.search(text):
        return "publication", None
    return None, None


def improvement_requested(message: str) -> bool:
    return bool(_IMPROVE.search(message))


def _width_variant(message: str) -> str:
    if re.search(r"\b(?:double|two|2)[- ]?columns?\b|\bfull[- ](?:width|page)\b", message, re.I):
        return "double"
    if re.search(r"\b(?:1\.5|one and a half)[- ]?columns?\b", message, re.I):
        return "1.5"
    return "single"


def edits(key: str, request: AssistantRequest) -> tuple[list[StyleEdit], str]:
    """The style edits for a preset on this plot, and a sentence describing them."""
    from app.services.assistant_plot_parts import condition_colours, style_controls

    preset = PRESETS[key]
    available = style_controls(request)
    result: list[StyleEdit] = []

    def add(element: str, prop: str, value):
        if (element, prop) in available:
            result.append(StyleEdit(element=element, property=prop, operation="set", value=value))

    for (element, prop), control in available.items():
        if prop == "font family" and (element == "all text" or control.value not in {"", preset.font}):
            if preset.font in control.options:
                add(element, prop, preset.font)
    for element, size in preset.sizes.items():
        add(element, "label size" if element == "value labels" else "size", f"{size:g}")
    variant = _width_variant(request.message)
    width = preset.widths_cm[variant]
    add("plot", "width", f"{width:g}")
    current_width, current_height = available.get(("plot", "width")), available.get(("plot", "height"))
    try:
        ratio = (float(str(current_height.value)) / float(str(current_width.value))
                 if current_width and current_height else None)
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = None
    if ratio:
        add("plot", "height", f"{max(2.0, round(width * ratio, 1)):g}")
    dpi = available.get(("plot", "dpi"))
    try:
        if dpi is not None and float(str(dpi.value)) < preset.min_dpi:
            add("plot", "dpi", str(preset.min_dpi))
    except (TypeError, ValueError):
        add("plot", "dpi", str(preset.min_dpi))
    if preset.frame_width is not None:
        add("frame", "width", f"{preset.frame_width:g}")
    if preset.grid_off:
        add("frame and grid / grid lines", "show", False)
    if preset.palette:
        for index, name in enumerate(condition_colours(request)):
            add(f"condition:{name}", "color", OKABE_ITO[index % len(OKABE_ITO)])
    for key_pair, value in preset.suggestions.items():
        element, prop = key_pair.split("|")
        add(element, prop, value)
    columns = {"single": "single-column", "1.5": "1.5-column", "double": "double-column"}[variant]
    if preset.stated:
        summary = (f"Applied {preset.label}'s figure specifications ({columns}, {width:g} cm wide): "
                   + ", ".join(preset.stated) + f". Source: {preset.source}.")
    else:
        summary = f"Applied the {preset.label} ({columns}, {width:g} cm wide). Source: {preset.source}."
    if preset.suggestions:
        summary += " Removing the top and right frame lines and the white background are suggestions, not requirements."
    if preset.not_settable:
        summary += " Not set here: " + "; ".join(preset.not_settable) + "."
    return result, summary


def catalogue() -> list[dict]:
    """What the planner sees about the presets."""
    return [{"preset": key, "label": preset.label, "requirements": preset.stated or ["suggested style"],
             "widthsCm": preset.widths_cm} for key, preset in PRESETS.items()]


def unchecked_journal_answer(name: str) -> str:
    return (f"I don't have a checked figure specification for {name}, so I won't present guesses as its "
            "requirements. I can apply Nature's or Cell Press's specifications, or a general publication style "
            "(sans-serif 7-9 pt text, single-column width, colour-blind-safe colours). Which would you like?")
