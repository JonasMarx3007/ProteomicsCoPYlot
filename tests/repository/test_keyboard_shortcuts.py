"""The global keyboard shortcuts, and what they must not take from the browser.

A shortcut is a promise about a key that the browser, the operating system and
other applications also have opinions about. These tests pin the two the tool
claims and the three properties that keep them from misbehaving:

* they are matched on `event.code`, the physical key, so a QWERTZ or AZERTY
  keyboard fires the same shortcut as QWERTY -- `event.key` for the same
  physical key is a different letter there;
* Shift is part of the shortcut, not a modifier to ignore, so Ctrl+Shift+S
  stays the browser's, and the advanced-panel key avoids Ctrl+Shift+A,
  which Chrome answers with its own tab search;
* Alt-combinations are left alone entirely, because they open menus on Windows
  and produce characters on macOS.

The documented list lives in `docs/` and in the review report; if a shortcut is
added here it has to be added there too, which is what the last test checks.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

APP = ROOT / "frontend" / "src" / "App.tsx"
SETTINGS = ROOT / "frontend" / "src" / "features" / "settings" / "SettingsPage.tsx"


def _handler() -> str:
    """The body of the one global keydown handler."""
    source = APP.read_text(encoding="utf-8")
    start = source.index("function onKeyDown(event: KeyboardEvent)")
    end = source.index('window.addEventListener("keydown", onKeyDown)', start)
    return source[start:end]


def test_there_is_exactly_one_global_keydown_handler() -> None:
    """Two handlers on `window` means two shortcuts can fire for one press."""
    source = APP.read_text(encoding="utf-8")
    assert source.count('window.addEventListener("keydown", onKeyDown)') == 1
    # The unsaved-changes baseline listens once with `once: true`; that is not a
    # shortcut and must stay the only other keydown listener on window here.
    others = re.findall(r'window\.addEventListener\("keydown", (\w+)', source)
    assert sorted(others) == ["initializeBaseline", "onKeyDown"], others


def test_quick_save_is_ctrl_or_cmd_s_without_shift() -> None:
    body = _handler()
    assert 'event.code === "KeyS" && !event.shiftKey' in body, (
        "Ctrl+S must save and Ctrl+Shift+S must be left to the browser"
    )
    assert "handleQuickSaveRef.current(false)" in body


def test_quick_save_does_not_work_in_a_viewer() -> None:
    """It exports the whole session, which the backend now refuses anyway.

    A viewer has nothing to save and no business taking the matrices with them;
    `POST /api/restore/export` is in the viewer deny list, so leaving the
    shortcut bound would give a collaborator a key that silently fails.
    """
    body = _handler()
    assert 'event.code === "KeyS" && !event.shiftKey && !IS_VIEWER_MODE' in body

    from app.main import _VIEWER_DENIED_EXACT

    assert ("POST", "/api/restore/export") in _VIEWER_DENIED_EXACT, (
        "the shortcut is gated on the frontend; the endpoint has to be gated too"
    )


def test_the_advanced_plot_toggle_still_works_in_a_viewer() -> None:
    """A collaborator styles a publication-ready figure from a published project."""
    body = _handler()
    branch = body[body.index('event.code === "KeyE"') :]
    assert "IS_VIEWER_MODE" not in branch, (
        "the advanced plot panel is how a viewer makes a figure publishable; "
        "it must not be gated on analysis mode"
    )


def test_the_advanced_plot_panel_toggles_on_ctrl_or_cmd_shift_e() -> None:
    body = _handler()
    assert 'event.code === "KeyE" && event.shiftKey' in body, (
        "the advanced panel shortcut is Ctrl/Cmd+Shift+E"
    )
    assert '"KeyA"' not in body, (
        "Ctrl/Cmd+Shift+A is Chrome's tab search; the browser answers it first, "
        "so binding it here gives the user a key that appears to do nothing"
    )
    assert "setAdvancedPlotMode(!getAdvancedPlotMode())" in body, (
        "the shortcut must go through the shared setter, which broadcasts the "
        "change to every page listening; setting the flag directly leaves the "
        "panels showing the old mode"
    )


def test_every_shortcut_requires_ctrl_or_cmd_and_never_alt() -> None:
    body = _handler()
    assert "if (event.altKey) return;" in body
    assert "if (!(event.ctrlKey || event.metaKey)) return;" in body
    assert "if (event.repeat) return;" in body, "a held key must fire once"


def test_no_shortcut_matches_on_the_printed_letter() -> None:
    """`event.key` is the letter the layout produces; `code` is the key."""
    code = "\n".join(
        line for line in _handler().splitlines() if not line.strip().startswith("//")
    )
    assert "event.key" not in code, (
        "match on event.code so the shortcut survives a non-US keyboard layout"
    )


def test_the_settings_switch_follows_the_shortcut() -> None:
    """Toggling by keyboard with Settings open must move the switch."""
    source = SETTINGS.read_text(encoding="utf-8")
    assert '"copylot:advancedPlotModeChanged"' in source, (
        "the switch would keep showing the old position after Ctrl+Shift+E"
    )
    assert "setAdvancedPlots(getAdvancedPlotMode())" in source


def test_the_settings_switch_describes_what_it_does() -> None:
    source = SETTINGS.read_text(encoding="utf-8")
    assert "will use it when they are built" not in source, (
        "the advanced controls exist; the description outlived them"
    )
    assert "Ctrl/Cmd + Shift + E" in source, "the shortcut has to be discoverable"
