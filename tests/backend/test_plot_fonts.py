"""The face a figure is drawn in.

A font is the one plot setting that can be accepted, applied, and still not
happen: matplotlib answers a family it cannot find with a warning on stderr and
a DejaVu substitution, and returns a perfectly good PNG. So these tests check
two different things -- that the right family reaches the right artist, and that
the family is one this machine can actually draw.
"""

from __future__ import annotations

import pytest
from matplotlib import pyplot as plt

from app.services.plot_styling import (
    FONT_ELEMENT_KEYS,
    PLOT_FONTS,
    advanced_plotly_layout,
    apply_advanced_axes,
    installed_family,
    mpl_font_family,
    plotly_font_family,
    resolve_font,
    verify_fonts_installed,
)


def test_no_font_setting_leaves_every_plot_alone() -> None:
    """None, not a default: a plot that never asks keeps what it always had."""
    assert resolve_font({}) is None
    assert resolve_font(None, "title") is None
    assert mpl_font_family({}) is None
    assert plotly_font_family({}, "legend") is None


def test_the_global_font_reaches_every_element() -> None:
    settings = {"fontFamily": "times"}
    for element in [None, *FONT_ELEMENT_KEYS]:
        assert resolve_font(settings, element) == PLOT_FONTS["times"]


def test_an_element_may_disagree_with_the_global_font() -> None:
    settings = {"fontFamily": "times", "titleFontFamily": "courier"}
    assert resolve_font(settings, "title") == PLOT_FONTS["courier"]
    # Everything else still follows the global one, which is the point of
    # having a global one.
    assert resolve_font(settings, "legend") == PLOT_FONTS["times"]
    assert resolve_font(settings) == PLOT_FONTS["times"]


def test_an_empty_element_choice_falls_back_rather_than_clearing() -> None:
    """The panel's "Same as all text" sends "", which must not mean "no font"."""
    settings = {"fontFamily": "times", "titleFontFamily": ""}
    assert resolve_font(settings, "title") == PLOT_FONTS["times"]


def test_a_name_that_is_not_offered_is_ignored() -> None:
    """A stale save state, or a hand-edited URL, must not reach matplotlib."""
    assert resolve_font({"fontFamily": "Comic Sans MS"}) is None
    assert resolve_font({"fontFamily": "times", "titleFontFamily": "nonsense"}, "title") == (
        PLOT_FONTS["times"]
    )


@pytest.mark.parametrize("name", sorted(PLOT_FONTS))
def test_every_offered_font_resolves_to_something_installed(name: str) -> None:
    """The check that makes the list honest rather than decorative."""
    from matplotlib import font_manager

    families, _ = PLOT_FONTS[name]
    available = {font.name for font in font_manager.fontManager.ttflist}
    assert installed_family(families) in available


def test_container_font_probe_requires_first_choice_fonts() -> None:
    from matplotlib import font_manager

    available = {font.name for font in font_manager.fontManager.ttflist}
    missing = {families[0] for families, _ in PLOT_FONTS.values()} - available
    if missing:
        with pytest.raises(RuntimeError) as error:
            verify_fonts_installed()
        assert all(face in str(error.value) for face in missing)
    else:
        assert verify_fonts_installed().startswith("fonts ok:")


def test_desktop_font_resolution_uses_first_available_fallback(monkeypatch) -> None:
    from matplotlib import font_manager
    from types import SimpleNamespace

    monkeypatch.setattr(font_manager.fontManager, "ttflist", [
        SimpleNamespace(name="Arial"), SimpleNamespace(name="DejaVu Sans"),
    ])
    installed_family.cache_clear()
    try:
        assert installed_family(PLOT_FONTS["helvetica"][0]) == "Arial"
    finally:
        installed_family.cache_clear()


def test_the_face_reaches_the_title_labels_ticks_and_annotations() -> None:
    figure, axes = plt.subplots()
    try:
        axes.set_title("Title")
        axes.set_xlabel("X")
        axes.set_ylabel("Y")
        axes.plot([0, 1], [0, 1], label="series")
        axes.legend()
        axes.text(0.5, 0.5, "42")
        apply_advanced_axes(axes, {"fontFamily": "times"})

        wanted = installed_family(PLOT_FONTS["times"][0])
        assert axes.title.get_fontfamily() == [wanted]
        assert axes.xaxis.label.get_fontfamily() == [wanted]
        assert axes.yaxis.label.get_fontfamily() == [wanted]
        assert axes.get_xticklabels()[0].get_fontfamily() == [wanted]
        assert axes.texts[0].get_fontfamily() == [wanted]
        assert axes.get_legend().get_texts()[0].get_fontfamily() == [wanted]
    finally:
        plt.close(figure)


def test_one_element_can_be_drawn_in_another_face() -> None:
    figure, axes = plt.subplots()
    try:
        axes.set_title("Title")
        axes.set_xlabel("X")
        apply_advanced_axes(axes, {"fontFamily": "times", "titleFontFamily": "courier"})
        assert axes.title.get_fontfamily() == [installed_family(PLOT_FONTS["courier"][0])]
        assert axes.xaxis.label.get_fontfamily() == [installed_family(PLOT_FONTS["times"][0])]
    finally:
        plt.close(figure)


def test_the_face_actually_changes_what_is_drawn() -> None:
    """Two faces, two different pictures -- the check a mocked family passes.

    Everything above proves the setting arrives. This proves it has an effect:
    the same word rendered in a serif and in a monospace face cannot occupy the
    same pixels.
    """

    def render(font: str) -> bytes:
        figure, axes = plt.subplots(figsize=(2, 1))
        try:
            axes.set_title("Coverage")
            axes.set_xticks([])
            axes.set_yticks([])
            apply_advanced_axes(axes, {"fontFamily": font})
            figure.canvas.draw()
            return figure.canvas.tostring_argb()
        finally:
            plt.close(figure)

    assert render("times") != render("courier")


def test_the_plotly_layout_carries_the_family_and_its_overrides() -> None:
    layout = advanced_plotly_layout(
        {"fontFamily": "helvetica", "legendFontFamily": "courier"}
    )
    assert layout["font"]["family"] == PLOT_FONTS["helvetica"][1]
    assert layout["legend"]["font"]["family"] == PLOT_FONTS["courier"][1]


def test_bold_no_longer_changes_the_typeface() -> None:
    """Bold used to be faked by swapping the family to Arial Black, which meant
    asking for a bold title silently restyled it -- and would now fight the font
    the user chose."""
    layout = advanced_plotly_layout(
        {"fontFamily": "times", "titleElement": {"bold": True, "italic": True}}
    )
    assert layout["title_font"]["weight"] == "bold"
    assert layout["title_font"]["style"] == "italic"
    assert "Arial Black" not in str(layout)
    assert layout["font"]["family"] == PLOT_FONTS["times"][1]


def test_a_legend_size_no_longer_drops_the_legend_colour() -> None:
    """Setting both used to replace the font dict and lose the colour."""
    layout = advanced_plotly_layout({"legendFontSize": 14, "legendTextColor": "#ff00ff"})
    assert layout["legend"]["font"] == {"color": "#ff00ff", "size": 14}
