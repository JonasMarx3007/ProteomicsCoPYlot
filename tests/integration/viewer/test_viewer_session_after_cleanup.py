"""A viewer session that cleanup emptied loads its project again.

Each viewer session loads the published project once and remembers that in a
marker. Session cleanup (24 h idle, or more sessions than the cap) discarded the
session's datasets but not the marker, so a browser that came back was told the
project was already loaded and shown an empty one. Cleanup now forgets the
marker, and the marker alone is no longer trusted when the stores are empty.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import session_cleanup, viewer_bootstrap
from app.services.dataset_store import reset_all_datasets, session_has_datasets
from app.services.session_context import reset_session_id, set_session_id

ROOT = Path(__file__).resolve().parents[3]
SESSION = "viewer-cleanup-under-test"


@pytest.fixture
def viewer_session(monkeypatch):
    monkeypatch.setattr(viewer_bootstrap, "viewer_mode_enabled", lambda: True)
    monkeypatch.setattr(viewer_bootstrap, "_resolve_config_path", lambda: ROOT / "tests" / "fixtures" / "viewer_config.json")
    # conftest turns isolation off for the suite; this test needs its own session.
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    token = set_session_id(SESSION)
    viewer_bootstrap.forget_viewer_session_bootstrap(SESSION)
    try:
        yield
    finally:
        session_cleanup._discard_session(SESSION)
        reset_session_id(token)


def test_cleanup_then_return_reloads_the_project(viewer_session):
    viewer_bootstrap.bootstrap_current_viewer_session()
    assert session_has_datasets(), "the project is loaded"

    session_cleanup._discard_session(SESSION)
    assert not session_has_datasets(), "cleanup empties the session"
    assert SESSION not in viewer_bootstrap._SESSION_BOOTSTRAP_CONFIG, "and forgets it was loaded"

    viewer_bootstrap.bootstrap_current_viewer_session()
    assert session_has_datasets(), "the returning browser gets the project again"


def test_an_emptied_store_is_reloaded_even_with_the_marker_set(viewer_session):
    viewer_bootstrap.bootstrap_current_viewer_session()
    reset_all_datasets()
    assert SESSION in viewer_bootstrap._SESSION_BOOTSTRAP_CONFIG
    viewer_bootstrap.bootstrap_current_viewer_session()
    assert session_has_datasets()


def test_a_loaded_session_is_not_reloaded(viewer_session, monkeypatch):
    viewer_bootstrap.bootstrap_current_viewer_session()
    loads = []
    monkeypatch.setattr(viewer_bootstrap, "load_viewer_state", lambda path: loads.append(path))
    for _ in range(3):
        viewer_bootstrap.bootstrap_current_viewer_session()
    assert loads == []
