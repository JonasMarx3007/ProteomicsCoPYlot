"""Room for new sessions is made from empty and stale sessions, never from active work."""
from __future__ import annotations

import time

import pandas as pd
import pytest

from app.services import dataset_store, session_cleanup
from app.services.session_context import reset_session_id, set_session_id


@pytest.fixture
def stores(monkeypatch):
    monkeypatch.setattr(session_cleanup, "_LAST_SEEN", {})
    monkeypatch.setattr(dataset_store, "_DATASET_SESSIONS", {})
    monkeypatch.setattr(session_cleanup, "_LAST_BUDGET_CHECK", 0.0)
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    monkeypatch.setenv("COPYLOT_SESSION_IDLE_SECONDS", "86400")
    discarded = []
    monkeypatch.setattr(session_cleanup, "_discard_session", discarded.append)
    return discarded


def _with_data(session_id: str, rows: int = 10) -> None:
    token = set_session_id(session_id)
    try:
        dataset_store.save_table_dataset("x.csv", "protein", pd.DataFrame({"ProteinNames": [f"P{i}" for i in range(rows)],
                                                                           "s1": range(rows)}))
    finally:
        reset_session_id(token)


def test_a_burst_of_empty_sessions_does_not_evict_active_work(stores, monkeypatch):
    monkeypatch.setenv("COPYLOT_MAX_SESSIONS", "3")
    _with_data("worker_session")
    session_cleanup.touch_and_cleanup_sessions("worker_session")
    for index in range(20):
        session_cleanup.touch_and_cleanup_sessions(f"anonymous_{index:02d}")
    assert "worker_session" in session_cleanup._LAST_SEEN
    assert "worker_session" not in stores
    assert len(session_cleanup._LAST_SEEN) <= 3


def test_stale_sessions_with_data_go_before_recent_ones(stores, monkeypatch):
    monkeypatch.setenv("COPYLOT_MAX_SESSIONS", "2")
    monkeypatch.setenv("COPYLOT_SESSION_PROTECT_SECONDS", "60")
    for name in ("stale_session", "recent_session"):
        _with_data(name)
    now = time.monotonic()
    session_cleanup._LAST_SEEN.update({"stale_session": now - 600, "recent_session": now - 10})
    session_cleanup.touch_and_cleanup_sessions("new_session_1")
    assert stores == ["stale_session"]
    session_cleanup.touch_and_cleanup_sessions("new_session_2")
    # The recent session is protected; the count may exceed the maximum instead.
    assert "recent_session" in session_cleanup._LAST_SEEN


def test_memory_budget_evicts_the_least_recently_used_idle_session(stores, monkeypatch):
    monkeypatch.setenv("COPYLOT_MAX_SESSIONS", "100")
    monkeypatch.setenv("COPYLOT_SESSION_PROTECT_SECONDS", "60")
    for name in ("old_big_session", "newer_big_session", "current_session"):
        _with_data(name, rows=20_000)
    one = session_cleanup.session_data_bytes("old_big_session")
    assert one > 0
    monkeypatch.setenv("COPYLOT_SERVER_MEMORY_MB", "1")
    monkeypatch.setattr(session_cleanup, "server_memory_budget_bytes", lambda: int(2.5 * one))
    now = time.monotonic()
    session_cleanup._LAST_SEEN.update({"old_big_session": now - 900, "newer_big_session": now - 300})
    session_cleanup.touch_and_cleanup_sessions("current_session")
    assert stores == ["old_big_session"]


def test_default_budget_is_generous():
    from app.services.upload_limits import _memory_capacity_bytes

    capacity = _memory_capacity_bytes()
    if capacity:
        assert session_cleanup.server_memory_budget_bytes() >= capacity // 2


def test_discard_revokes_both_auth_stores_only_for_the_target_session(monkeypatch):
    from app.services import tool_access, viewer_portal
    from app.services.session_context import get_session_id

    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    auth = viewer_portal.ViewerSessionAuth(project="example", project_label="Example")
    monkeypatch.setattr(tool_access, "_SESSION_AUTH", {"discarded", "retained"})
    monkeypatch.setattr(viewer_portal, "_SESSION_AUTH", {"discarded": auth, "retained": auth})
    monkeypatch.setattr(viewer_portal, "_BOOTSTRAPPED_SESSION_PROJECT", {
        "discarded": "example", "retained": "example",
    })
    token = set_session_id("retained")
    try:
        session_cleanup._discard_session("discarded")
        assert get_session_id() == "retained"
        assert tool_access._SESSION_AUTH == {"retained"}
        assert viewer_portal._SESSION_AUTH == {"retained": auth}
        assert viewer_portal._BOOTSTRAPPED_SESSION_PROJECT == {"retained": "example"}
    finally:
        reset_session_id(token)
