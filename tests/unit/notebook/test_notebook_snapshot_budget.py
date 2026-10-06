"""Notebook exports are kept per session, and a render that is a file download gets none.

The store used to have one byte budget for everybody: one session's report
(about 33 MB on the example data) evicted every other session's exports, so
their Export buttons failed. A session now evicts only its own oldest exports;
the server-wide ceiling sits far above one session's share.
"""
from __future__ import annotations

import pytest

from app.services.notebook_archive import NotebookRecipe
from app.services.notebook_snapshots import NotebookSnapshots
from app.services.notebook_source import NotebookSource


def _recipe(size: int) -> NotebookRecipe:
    return NotebookRecipe(plot_name="p", source=NotebookSource("", (), ()), calculation="", settings={},
        provenance={}, original_filename="", resources={"input.parquet": b"x" * size})


def test_one_session_cannot_evict_another_sessions_exports() -> None:
    store = NotebookSnapshots(max_bytes=1000, max_total_bytes=10_000)
    alice = [store.capture("alice", _recipe(300)) for _ in range(2)]
    for _ in range(5):
        store.capture("mallory", _recipe(800))
    for token in alice:
        assert store.get("alice", token).resources["input.parquet"] == b"x" * 300


def test_a_session_over_its_budget_drops_its_own_oldest_export() -> None:
    store = NotebookSnapshots(max_bytes=1000, max_total_bytes=10_000)
    first = store.capture("alice", _recipe(600))
    second = store.capture("alice", _recipe(600))
    with pytest.raises(KeyError):
        store.get("alice", first)
    assert store.get("alice", second)


def test_logout_and_reset_forget_the_sessions_exports() -> None:
    from app.services.notebook_qc import snapshots
    from app.services.notebook_snapshots import forget_session
    token = snapshots.capture("leaving", _recipe(10))
    forget_session("leaving")
    with pytest.raises(KeyError):
        snapshots.get("leaving", token)


def test_a_download_in_another_format_captures_no_export(client) -> None:
    rendered = client.get("/api/plots/qc/protein/boxplot.png")
    assert rendered.headers.get("x-copylot-notebook")
    downloaded = client.get("/api/plots/qc/protein/boxplot.png", params={"downloadFormat": "svg"})
    assert downloaded.status_code == 200
    assert "x-copylot-notebook" not in downloaded.headers


def test_an_export_still_in_use_does_not_expire() -> None:
    now = [0.0]
    store = NotebookSnapshots(ttl=10, clock=lambda: now[0])
    token = store.capture("alice", _recipe(10))
    now[0] = 8
    store.get("alice", token)
    now[0] = 15
    assert store.get("alice", token)


def test_completed_recipe_is_recounted_and_evicts_older_exports():
    from app.services.notebook_snapshots import PendingRecipe, recipe_size
    store = NotebookSnapshots(max_bytes=1500, max_total_bytes=3000)
    older = store.capture('alice', _recipe(700))
    pending = store.capture('alice', PendingRecipe(_recipe(10), lambda: _recipe(900)))
    result = store.get('alice', pending)
    assert store._entries[pending].size == recipe_size(result)
    with pytest.raises(KeyError):
        store.get('alice', older)


def test_completed_recipe_cannot_bypass_either_budget():
    from app.services.notebook_snapshots import PendingRecipe
    store = NotebookSnapshots(max_bytes=1000, max_total_bytes=2000)
    token = store.capture('alice', PendingRecipe(_recipe(10), lambda: _recipe(3000)))
    with pytest.raises(ValueError, match='memory limit'):
        store.get('alice', token)


def test_shared_retained_frames_count_once_and_old_frames_remain_accounted_for():
    import pandas as pd
    from app.services.notebook_snapshots import PendingRecipe, RetainedReplay
    frame = pd.DataFrame({'x': range(500)})
    frame_bytes = int(frame.memory_usage(deep=True).sum())
    store = NotebookSnapshots(max_bytes=frame_bytes + 1000, max_total_bytes=20_000)
    tokens = [store.capture('alice', PendingRecipe(_recipe(10), RetainedReplay(lambda: _recipe(10), (frame,))))
              for _ in range(2)]
    entries = list(store._entries.values())
    assert store._usage(entries) == frame_bytes + sum(entry.size for entry in entries)
    assert len(tokens) == len(entries) == 2
    with pytest.raises(ValueError, match='memory limit'):
        store.capture('alice', PendingRecipe(_recipe(10), RetainedReplay(lambda: _recipe(10), (pd.DataFrame({'x': range(10_000)}),))))


def test_defaults_scale_with_ram_and_explicit_limits_are_respected(monkeypatch):
    from app.services import notebook_limits
    for name in ('COPYLOT_NOTEBOOK_MEMORY_MB', 'COPYLOT_NOTEBOOK_SESSION_MEMORY_MB'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(notebook_limits, '_memory_capacity_bytes', lambda: 32 * 1024**3)
    assert notebook_limits.notebook_memory_budgets() == (4 * 1024**3, 8 * 1024**3)
    monkeypatch.setenv('COPYLOT_NOTEBOOK_MEMORY_MB', '6000')
    monkeypatch.setenv('COPYLOT_NOTEBOOK_SESSION_MEMORY_MB', '5000')
    assert notebook_limits.notebook_memory_budgets() == (5000 * 1024**2, 6000 * 1024**2)
