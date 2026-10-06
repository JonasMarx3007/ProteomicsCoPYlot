"""A published viewer project reloads when its config changes.

`bootstrap_current_viewer_session` loads a project once per browser session
and then does nothing, which is what keeps every later request cheap. It used to
remember that decision by the config file's *path*, so once a session had
bootstrapped there was no edit to `viewer_config.json` that could reach it: an
administrator could change a filter threshold, swap a data file or add a dataset,
reload their own page, and be served the project as it was when they first
opened it -- with nothing on screen to say the edit had not taken.

The modification time is part of the key now. An unchanged file is still loaded
once; a changed one is loaded again.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.services import viewer_bootstrap


@pytest.fixture
def viewer_session(monkeypatch, tmp_path):
    """A viewer session whose loads are counted rather than performed."""
    monkeypatch.setattr(viewer_bootstrap, "viewer_mode_enabled", lambda: True)
    monkeypatch.setattr(viewer_bootstrap, "get_session_id", lambda: "session-under-test")
    config = tmp_path / "viewer_config.json"
    config.write_text('{"datasets": {}}', encoding="utf-8")
    monkeypatch.setattr(viewer_bootstrap, "_resolve_config_path", lambda: config)
    loads: list[Path] = []
    monkeypatch.setattr(
        viewer_bootstrap, "load_viewer_state", lambda path: loads.append(Path(path))
    )
    # Loads are only counted here, so nothing fills the dataset store; report
    # it as loaded so these tests isolate the config-change rule.
    monkeypatch.setattr(viewer_bootstrap, "_session_still_loaded", lambda: True)
    viewer_bootstrap._SESSION_BOOTSTRAP_CONFIG.pop("session-under-test", None)
    yield config, loads
    viewer_bootstrap._SESSION_BOOTSTRAP_CONFIG.pop("session-under-test", None)


def test_an_unchanged_config_is_loaded_once(viewer_session) -> None:
    _config, loads = viewer_session
    for _ in range(5):
        viewer_bootstrap.bootstrap_current_viewer_session()
    assert len(loads) == 1, "the whole point of the marker is that it loads once"


def test_an_edited_config_is_loaded_again(viewer_session) -> None:
    config, loads = viewer_session
    viewer_bootstrap.bootstrap_current_viewer_session()
    assert len(loads) == 1

    config.write_text('{"datasets": {"HEK293": {}}}', encoding="utf-8")
    # Filesystems differ in mtime resolution; the tool must notice the edit, not
    # the clock, so the stamp is set explicitly rather than waited for.
    stamp = config.stat().st_mtime_ns + 1_000_000_000
    os.utime(config, ns=(stamp, stamp))

    viewer_bootstrap.bootstrap_current_viewer_session()
    assert len(loads) == 2, (
        "an edited viewer config never reached a session that had already "
        "bootstrapped, so the admin's change was invisible to every open viewer"
    )

    viewer_bootstrap.bootstrap_current_viewer_session()
    assert len(loads) == 2, "and it settles again once loaded"


def test_a_forced_reload_still_reloads_an_unchanged_config(viewer_session) -> None:
    """Login and the browser-session reset both force one."""
    _config, loads = viewer_session
    viewer_bootstrap.bootstrap_current_viewer_session()
    viewer_bootstrap.bootstrap_current_viewer_session(force_reload=True)
    assert len(loads) == 2


def test_the_marker_is_per_session(viewer_session, monkeypatch) -> None:
    _config, loads = viewer_session
    viewer_bootstrap.bootstrap_current_viewer_session()
    monkeypatch.setattr(viewer_bootstrap, "get_session_id", lambda: "another-session")
    try:
        viewer_bootstrap.bootstrap_current_viewer_session()
        assert len(loads) == 2, "a second browser must load the project for itself"
    finally:
        viewer_bootstrap._SESSION_BOOTSTRAP_CONFIG.pop("another-session", None)
