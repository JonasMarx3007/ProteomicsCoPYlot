from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[3]

from app.schemas.stats import VolcanoResultResponse
from app.services.runtime_cache import (
    UnfreezableArgument,
    _copy_for_caller,
    _freeze,
    cached_call,
    invalidate_runtime_cache,
    runtime_cache_version,
)
from app.services.session_context import set_session_id, reset_session_id


@pytest.fixture(autouse=True)
def _clean_cache():
    invalidate_runtime_cache("test", all_sessions=True)
    yield
    invalidate_runtime_cache("test", all_sessions=True)


def test_session_edits_preserve_other_sessions_cache_and_evidence(monkeypatch):
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    from app.services.assistant_snapshots import store_snapshot, read_snapshot

    token_a = set_session_id("cache-session-a")
    try:
        revision_a = runtime_cache_version()
        calls = []
        def compute():
            calls.append(1)
            return "A"
        assert cached_call("sessions", {}, compute) == "A"
        snapshot = store_snapshot({"answer": "A"})
        token_b = set_session_id("cache-session-b")
        try:
            invalidate_runtime_cache("B changed")
            assert cached_call("sessions", {}, lambda: "B") == "B"
            with pytest.raises(ValueError, match="expired"):
                read_snapshot(snapshot)
        finally:
            reset_session_id(token_b)
        assert runtime_cache_version() == revision_a
        assert cached_call("sessions", {}, compute) == "A"
        assert len(calls) == 1
        assert read_snapshot(snapshot) == {"answer": "A"}
        invalidate_runtime_cache("A changed")
        with pytest.raises(ValueError, match="expired"):
            read_snapshot(snapshot)
        cached_call("sessions", {}, compute)
        assert len(calls) == 2
    finally:
        reset_session_id(token_a)


@pytest.mark.parametrize("all_sessions", [False, True])
def test_invalidation_during_computation_does_not_cache_stale_results(all_sessions):
    def obsolete():
        invalidate_runtime_cache("changed during calculation", all_sessions=all_sessions)
        return "old"
    assert cached_call("in-flight", {}, obsolete) == "old"
    assert cached_call("in-flight", {}, lambda: "new") == "new"


@pytest.mark.parametrize("module,function", [
    ("runtime_cache", "invalidate_runtime_cache"),
    ("dataset_store", "reset_all_datasets"),
    ("annotation_store", "reset_all_annotations"),
    ("metadata_upload_store", "reset_all_uploaded_metadata"),
    ("condition_palette_store", "reset_condition_palettes"),
    ("peptide_metadata_store", "clear_peptide_metadata"),
])
def test_global_reset_invalidates_other_sessions(monkeypatch, module, function):
    from importlib import import_module
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    token = set_session_id("cache-session-a")
    try:
        revision = runtime_cache_version()
        cached_call("global-reset", {}, lambda: "old")
    finally:
        reset_session_id(token)
    reset = getattr(import_module(f"app.services.{module}"), function)
    reset(all_sessions=True)
    token = set_session_id("cache-session-a")
    try:
        assert runtime_cache_version() != revision
        assert cached_call("global-reset", {}, lambda: "new") == "new"
    finally:
        reset_session_id(token)


def test_other_session_invalidation_does_not_discard_in_flight_result(monkeypatch):
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    calls = []
    def compute():
        calls.append(1)
        token = set_session_id("other-session")
        try:
            invalidate_runtime_cache("other user edited")
        finally:
            reset_session_id(token)
        return "result"
    assert cached_call("in-flight-other", {}, compute) == "result"
    assert cached_call("in-flight-other", {}, compute) == "result"
    assert len(calls) == 1


def _response(rows: int = 50) -> VolcanoResultResponse:
    row = {"ProteinNames": "P1", "log2FC": 1.0, "pval": 0.01}
    return VolcanoResultResponse(
        kind="protein",
        sourceUsed="filtered",
        labelColumn="ProteinNames",
        totalRows=rows,
        upregulatedCount=1,
        downregulatedCount=0,
        notSignificantCount=rows - 1,
        rows=[dict(row) for _ in range(rows)],
        warnings=[],
    )


def test_mutating_a_returned_response_does_not_affect_later_callers() -> None:
    first = cached_call("demo", {"a": 1}, _response)
    first.rows.clear()
    first.upregulatedCount = 9999
    second = cached_call("demo", {"a": 1}, _response)
    assert len(second.rows) == 50, "the cache served a mutated object"
    assert second.upregulatedCount == 1


def test_mutating_a_returned_dataframe_does_not_affect_later_callers() -> None:
    build = lambda: pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    first = cached_call("frame", {"a": 1}, build)
    first.iloc[0, 0] = 999.0
    second = cached_call("frame", {"a": 1}, build)
    assert second.iloc[0, 0] == 1.0


def test_opting_out_still_shares_the_object() -> None:
    first = cached_call("shared", {"a": 1}, _response, copy_result=False)
    second = cached_call("shared", {"a": 1}, _response, copy_result=False)
    assert first is second


@pytest.mark.parametrize(
    "value",
    [b"\x89PNG" + b"x" * 1000, "<html>" + "y" * 1000, 42, 3.5, True, None],
)
def test_immutable_values_are_returned_without_copying(value: object) -> None:
    assert _copy_for_caller(value) is value


def test_copying_a_large_response_is_not_slower_than_recomputing_it() -> None:
    payload = _response(rows=4000)
    start = time.perf_counter()
    _copy_for_caller(payload)
    duration = time.perf_counter() - start
    assert duration < 1.0, f"copying a cached response took {duration:.2f}s"


def test_dataframe_copy_is_independent_and_cheap() -> None:
    frame = pd.DataFrame(np.random.default_rng(0).normal(size=(2000, 10)))
    copied = _copy_for_caller(frame)
    copied.iloc[0, 0] = 12345.0
    assert frame.iloc[0, 0] != 12345.0


def test_dataframes_are_refused_as_cache_keys() -> None:
    with pytest.raises(UnfreezableArgument):
        _freeze(pd.DataFrame({"x": range(200)}))


def test_arbitrary_objects_are_refused_as_cache_keys() -> None:
    class Opaque:
        pass

    with pytest.raises(UnfreezableArgument):
        _freeze(Opaque())


def test_unkeyable_arguments_skip_the_cache_instead_of_colliding() -> None:
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return calls["n"]

    left = pd.DataFrame({"x": range(200)})
    right = left.copy()
    right.iloc[100, 0] = -999

    first = cached_call("unkeyable", {"frame": left}, factory)
    second = cached_call("unkeyable", {"frame": right}, factory)
    assert calls["n"] == 2, "a DataFrame argument was cached and could collide"
    assert first != second


@pytest.mark.parametrize(
    "value",
    ["text", 1, 2.5, True, None, b"bytes", ["a", 1], ("a", 1), {"k": "v"}, {1, 2}],
)
def test_ordinary_arguments_still_freeze(value: object) -> None:
    _freeze(value)


def test_pydantic_arguments_still_freeze() -> None:
    from app.schemas.stats import VolcanoRequest

    payload = VolcanoRequest(kind="protein", condition1="A", condition2="B")
    assert _freeze(payload) == _freeze(payload)


def test_equivalent_keys_hit_and_different_keys_miss() -> None:
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return calls["n"]

    cached_call("keys", {"a": 1, "b": "x"}, factory)
    cached_call("keys", {"b": "x", "a": 1}, factory)
    assert calls["n"] == 1
    cached_call("keys", {"a": 2, "b": "x"}, factory)
    assert calls["n"] == 2


@pytest.mark.parametrize(
    "left,right",
    [
        (True, 1),
        (False, 0),
        (1, 1.0),
        ({"x": True}, {"x": 1}),
        ([True, 2], [1, 2]),
    ],
    ids=["true-vs-1", "false-vs-0", "int-vs-float", "in-a-dict", "in-a-list"],
)
def test_values_python_calls_equal_are_still_different_keys(left, right) -> None:
    """`True == 1` and `1 == 1.0`, and equal values hash equally.

    The `advanced` plot settings arrive as untyped JSON straight off the query
    string, so `{"headerText": true}` and `{"headerText": 1}` are two different
    instructions -- `advanced_text` renders one as "True" and the other as
    "1" -- that Python considers the same key. Without tagging the type the
    second request would be served the first one's rendered figure.
    """
    assert _freeze(left) != _freeze(right), (left, right)


def test_a_boolean_and_an_integer_do_not_share_a_cache_entry() -> None:
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return calls["n"]

    cached_call("bools", {"advanced": {"headerText": True}}, factory)
    cached_call("bools", {"advanced": {"headerText": 1}}, factory)
    assert calls["n"] == 2, "the integer request was served the boolean's result"
