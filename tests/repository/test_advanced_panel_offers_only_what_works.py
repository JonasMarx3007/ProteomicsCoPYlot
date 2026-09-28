"""A card in the advanced panel changes something, or it is not shown.

The panel writes settings into a query parameter; the renderers read them. When
a card is shown for a plot whose renderer reads none of its keys, the user sets
a value, the plot redraws, and nothing moves -- which is worse than the control
not being there, because it teaches them the panel does not work.

This is checked in two directions:

* the keys the panel can write must all be read by some renderer, so a control
  cannot be added with nothing behind it; and
* the keys the renderers read must all be writable, so a renderer cannot be
  taught to read a setting nobody can set.

The per-plot visibility is a separate, weaker rule, and it is enforced by naming
the plots rather than by inference -- which card suits which figure is a
judgement, and a test that guesses it would be wrong in both directions.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PANEL = ROOT / "frontend" / "src" / "components" / "plots" / "AdvancedPlotOptions.tsx"
APP = ROOT / "frontend" / "src" / "App.tsx"
SERVICES = ROOT / "backend" / "app" / "services"
TYPES = ROOT / "frontend" / "src" / "lib" / "types.ts"

RENDERER_MODULES = [
    "plot_styling.py",
    "plot_images.py",
    "stats_tools.py",
    "single_protein_tools.py",
    "phospho_tools.py",
    "comparison_tools.py",
    "completeness_tools.py",
    "peptide_tools.py",
    "qc_tools.py",
]

# Keys the backend resolves through a helper rather than by name, or that are
# structural rather than cosmetic. Each needs a reason.
NOT_READ_BY_NAME = {
    # Read through `apply_advanced_axes` / `advanced_plotly_layout`.
    "titleElement", "xLabelElement", "yLabelElement",
}


def _panel_keys() -> set[str]:
    """Every settings key the panel writes."""
    source = PANEL.read_text(encoding="utf-8")
    keys: set[str] = set()
    for match in re.finditer(r"patch(?:GeneralMarker)?\(\{\s*([A-Za-z_]\w*)\s*:", source):
        keys.add(match.group(1))
    for match in re.finditer(r'patchConditionMarker\(\s*"(\w+)"', source):
        keys.add(match.group(1))
    return keys


def _renderer_text() -> str:
    return "\n".join(
        (SERVICES / module).read_text(encoding="utf-8") for module in RENDERER_MODULES
    )


def test_the_panel_writes_a_plausible_number_of_keys() -> None:
    assert len(_panel_keys()) > 25, "the key scan stopped matching; fix it before trusting it"


def test_every_key_the_panel_writes_is_read_by_a_renderer() -> None:
    renderers = _renderer_text()
    unread = sorted(
        key
        for key in _panel_keys()
        if key not in NOT_READ_BY_NAME and f'"{key}"' not in renderers
    )
    assert not unread, (
        "the panel can set these and no renderer reads them, so the plot does "
        f"not change: {unread}"
    )


def test_every_marker_key_a_renderer_reads_can_be_set() -> None:
    """The reverse: a renderer reading a setting nobody can write."""
    renderers = _renderer_text()
    declared = TYPES.read_text(encoding="utf-8")
    read = {
        match.group(1)
        for match in re.finditer(r'_advanced_\w+\([^,]+,\s*"(\w+)"', renderers)
    }
    read |= {
        match.group(1)
        for match in re.finditer(r'group_override\([^,]+,\s*"(\w+)"', renderers)
    }
    marker_keys = {key for key in read if key.lower().startswith(("marker", "conditionmarker"))}
    assert marker_keys, "no marker keys found; the scan is broken"
    undeclared = sorted(key for key in marker_keys if f"{key}?:" not in declared)
    assert not undeclared, (
        f"renderers read these and the settings type does not declare them: {undeclared}"
    )


def test_the_shape_vocabularies_match() -> None:
    """One shape list, or the panel offers a shape the backend cannot draw."""
    panel = PANEL.read_text(encoding="utf-8")
    block = panel[panel.index("const MARKER_SHAPE_OPTIONS") : panel.index("const MARKER_OVERRIDE_MAPS")]
    offered = set(re.findall(r'value: "([\w-]+)"', block))

    backend = (SERVICES / "plot_styling.py").read_text(encoding="utf-8")
    known = set(
        re.findall(
            r'^\s+"([\w-]+)": \("[^"]+", "[^"]+"\),',
            backend[backend.index("MARKER_SHAPES: dict") : backend.index("DEFAULT_MARKER_SHAPE")],
            re.M,
        )
    )
    assert offered == known, (
        f"panel offers {sorted(offered - known)}, backend knows {sorted(known - offered)}"
    )


def test_a_general_point_setting_clears_its_per_condition_overrides() -> None:
    """The whole behaviour of the card, in one function."""
    panel = PANEL.read_text(encoding="utf-8")
    block = panel[
        panel.index("function patchGeneralMarker") : panel.index("function patchConditionMarker")
    ]
    assert "MARKER_OVERRIDE_MAPS[key]" in block
    assert "cleared[mapKey] = {}" in block
    assert "volcanoUpSize" in block and "volcanoNsAlpha" in block, (
        "the volcano's three classes are the same idea with fixed names, so a "
        "general size or opacity has to clear them too"
    )


def test_the_general_point_controls_all_go_through_it() -> None:
    panel = PANEL.read_text(encoding="utf-8")
    for key in ("markerSize", "markerAlpha", "markerEdgeWidth", "markerColor", "markerEdgeColor", "markerShape"):
        assert f"patchGeneralMarker({{ {key}" in panel, (
            f"{key} is set with plain `patch`, so it would leave the per-condition "
            "overrides in place and appear to do nothing"
        )


def test_a_plot_with_no_figure_gets_no_panel() -> None:
    app = APP.read_text(encoding="utf-8")
    assert 'activePeptideTab === "sequenceCoverage" ? null' in app, (
        "sequence coverage draws an HTML map, not a figure; the styling panel "
        "has nothing to act on there"
    )


def test_the_plots_without_a_legend_do_not_offer_legend_controls() -> None:
    """Named, not inferred: these were checked against their renderers."""
    app = APP.read_text(encoding="utf-8")
    # The same keys also appear in the switch that picks each plot's control
    # defaults; only the visible-controls switch decides which cards are shown.
    app = app[app.index("const activeAdvancedVisibleControls"):]
    for key in ("comparison:venn", "comparison:pearson", "stats:ora", "phospho:distribution"):
        start = app.index(f'case "{key}":')
        block = app[start : app.index("case ", start + 10)]
        assert "legendControls: false" in block, f"{key} still offers a legend card"
