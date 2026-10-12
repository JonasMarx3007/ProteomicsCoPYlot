"""A published project is read once per config version and shared, each session with its own copy."""
from __future__ import annotations

import os
import json
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
import pytest

from app.services import annotation_store, dataset_store, viewer_bootstrap, viewer_portal
from app.services.session_context import reset_session_id, set_session_id

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "tests" / "fixtures" / "viewer_config.json"


@pytest.fixture
def counted(monkeypatch):
    viewer_bootstrap.forget_shared_viewer_templates()
    monkeypatch.setenv("COPYLOT_SESSION_ISOLATION", "1")
    calls = []
    original = viewer_bootstrap.load_viewer_state

    def counting(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(viewer_bootstrap, "load_viewer_state", counting)
    yield calls
    viewer_bootstrap.forget_shared_viewer_templates()


def _in_session(session_id, callback):
    token = set_session_id(session_id)
    try:
        return callback()
    finally:
        reset_session_id(token)


def test_two_visitors_share_one_load_and_keep_separate_copies(counted):
    for name in ("visitor_one_session", "visitor_two_session"):
        result = _in_session(name, lambda: viewer_bootstrap.load_viewer_state_shared(CONFIG))
        assert result.loaded_datasets
    assert len(counted) == 1
    one = _in_session("visitor_one_session", lambda: annotation_store.get_annotation("protein"))
    two = _in_session("visitor_two_session", lambda: annotation_store.get_annotation("protein"))
    assert one is not two and one.log2_data is not two.log2_data
    assert one.log2_data.equals(two.log2_data)
    column = one.metadata["sample"].iloc[0]
    before = float(two.log2_data[column].iloc[0])
    one.log2_data.loc[one.log2_data.index[0], column] = -999.0
    assert float(two.log2_data[column].iloc[0]) == before
    # The template is not a session the cleanup counts.
    assert not any(key.startswith("viewertemplate_") for key in dataset_store._DATASET_SESSIONS)
    for name in ("visitor_one_session", "visitor_two_session"):
        _in_session(name, dataset_store.reset_all_datasets)
        _in_session(name, annotation_store.reset_all_annotations)


def test_an_edited_config_is_read_again(counted, tmp_path):
    copy = tmp_path / "viewer_config.json"
    text = CONFIG.read_text(encoding="utf-8")
    base = CONFIG.parent
    import json

    payload = json.loads(text)
    for dataset in payload["datasets"].values():
        for key, value in list(dataset.items()):
            if isinstance(value, str) and key.endswith("_file"):
                dataset[key] = str((base / value).resolve())
        for profile in dataset.get("metadata_profiles", {}).values():
            for key, value in list(profile.items()):
                if isinstance(value, str) and key.endswith("_file"):
                    profile[key] = str((base / value).resolve())
    copy.write_text(json.dumps(payload), encoding="utf-8")
    _in_session("visitor_three_session", lambda: viewer_bootstrap.load_viewer_state_shared(copy))
    stamp = copy.stat().st_mtime_ns + 1_000_000_000
    os.utime(copy, ns=(stamp, stamp))
    _in_session("visitor_three_session", lambda: viewer_bootstrap.load_viewer_state_shared(copy))
    assert len(counted) == 2
    _in_session("visitor_three_session", dataset_store.reset_all_datasets)
    _in_session("visitor_three_session", annotation_store.reset_all_annotations)


@pytest.mark.parametrize("portal", [False, True])
def test_forced_refresh_reads_changed_data_without_config_edit(counted, tmp_path, monkeypatch, portal):
    package = json.loads(CONFIG.read_text(encoding="utf-8"))["datasets"]["HEK293"]
    source = pd.read_csv(CONFIG.parent / package["protein_file"], sep="\t", nrows=10)
    data_path = tmp_path / "protein.tsv"
    source.to_csv(data_path, sep="\t", index=False)
    package = {
        "protein_file": str(data_path),
        "metadata_profiles": {"example": {
            "meta_file": str((CONFIG.parent / package["metadata_profiles"]["WT_vs_GRK"]["meta_file"]).resolve()),
        }},
        "imputation": {"mode": "none"},
        "log2_transform_protein": True,
    }
    config = tmp_path / "viewer_config.json"
    config.write_text(json.dumps({"datasets": {"example": package}}), encoding="utf-8")
    stamp = config.stat().st_mtime_ns
    monkeypatch.setattr(viewer_bootstrap, "viewer_mode_enabled", lambda: True)
    monkeypatch.setattr(viewer_bootstrap, "_resolve_config_path", lambda: config)
    monkeypatch.setattr(viewer_portal, "resolve_viewer_project_config", lambda project: config)
    monkeypatch.setattr(viewer_bootstrap, "_SESSION_BOOTSTRAP_CONFIG", {})
    monkeypatch.setattr(viewer_portal, "_BOOTSTRAPPED_SESSION_PROJECT", {})

    def load(force=False):
        if portal:
            viewer_portal._load_project_into_current_session("example", force_reload=force)
        else:
            viewer_bootstrap.bootstrap_current_viewer_session(force_reload=force)

    def values():
        annotation = annotation_store.get_annotation("protein")
        return annotation.log2_data[annotation.metadata["sample"].tolist()].copy()

    sessions = ("refresh_first", "refresh_second", "refresh_third")
    try:
        for session in sessions[:2]:
            _in_session(session, load)
        before = _in_session(sessions[0], values)
        assert len(counted) == 1
        source.iloc[:, 8:] *= 2
        source.to_csv(data_path, sep="\t", index=False)
        assert config.stat().st_mtime_ns == stamp
        _in_session(sessions[0], load)
        assert len(counted) == 1
        _in_session(sessions[0], lambda: load(True))
        after = _in_session(sessions[0], values)
        assert not before.equals(after)
        pd.testing.assert_frame_equal(_in_session(sessions[1], values), before)
        _in_session(sessions[2], load)
        pd.testing.assert_frame_equal(_in_session(sessions[2], values), after)
        assert len(counted) == 2
    finally:
        for session in sessions:
            _in_session(session, viewer_portal._reset_current_session_data)


def test_failed_rebuild_keeps_cached_template_and_cleans_temporary_session(counted, monkeypatch):
    session = "refresh_failure"
    try:
        _in_session(session, lambda: viewer_bootstrap.load_viewer_state_shared(CONFIG))
        template = next(iter(viewer_bootstrap._SHARED_TEMPLATES.values()))
        original = viewer_bootstrap.load_viewer_state

        def fail_after_loading(path):
            original(path)
            raise RuntimeError("Failed rebuild")

        monkeypatch.setattr(viewer_bootstrap, "load_viewer_state", fail_after_loading)
        with pytest.raises(RuntimeError, match="Failed rebuild"):
            _in_session(session, lambda: viewer_bootstrap.load_viewer_state_shared(CONFIG, force_reload=True))
        assert next(iter(viewer_bootstrap._SHARED_TEMPLATES.values())) is template
        assert not any(key.startswith("viewertemplate_") for key in dataset_store._DATASET_SESSIONS)
        _in_session(session, lambda: viewer_bootstrap.load_viewer_state_shared(CONFIG))
        assert len(counted) == 2
    finally:
        _in_session(session, viewer_portal._reset_current_session_data)


def test_new_authenticated_visitors_reuse_shared_project(counted, monkeypatch):

    sessions = ("cached_login_one", "cached_login_two")
    pending = iter(sessions)

    @contextmanager
    def rotation():
        session = next(pending)
        token = set_session_id(session)
        try:
            yield session
        finally:
            reset_session_id(token)

    monkeypatch.setattr(viewer_portal, "authenticated_session_rotation", rotation)  # bound at import
    monkeypatch.setattr(viewer_portal, "resolve_viewer_project_config", lambda project: CONFIG)
    monkeypatch.setattr(viewer_portal, "_BOOTSTRAPPED_SESSION_PROJECT", {})
    monkeypatch.setattr(viewer_portal, "_SESSION_AUTH", {})
    try:
        for _ in sessions:
            viewer_portal._initialize_authenticated_viewer("example", "Example")
        assert len(counted) == 1
        for session in sessions:
            assert _in_session(session, viewer_portal.viewer_session_authenticated)
            assert _in_session(session, lambda: annotation_store.get_annotation("protein")) is not None
    finally:
        for session in sessions:
            _in_session(session, viewer_portal._reset_current_session_data)
