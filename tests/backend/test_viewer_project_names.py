from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.viewer_bootstrap import (
    PROJECT_ROOT,
    _project_viewer_config_candidates,
    resolve_viewer_project_config,
)
from app.services.viewer_portal import _normalize_project_name

TRAVERSING = ["..", ".", "...", "....", "../", "..\\"]
LEGITIMATE = ["good_name", "a.b", "v1.2-final", "example_project", "run-2024_01", "x"]


@pytest.mark.parametrize("name", TRAVERSING)
def test_dot_only_names_are_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        _normalize_project_name(name)
    assert resolve_viewer_project_config(name) is None


@pytest.mark.parametrize("name", LEGITIMATE)
def test_legitimate_names_still_accepted(name: str) -> None:
    assert _normalize_project_name(name) == name


@pytest.mark.parametrize("name", LEGITIMATE)
def test_accepted_names_stay_inside_the_viewer_directory(name: str) -> None:
    viewer_root = (PROJECT_ROOT / "viewer_data").resolve()
    for candidate in _project_viewer_config_candidates(name):
        resolved = candidate.resolve()
        assert viewer_root in resolved.parents or resolved.parent == viewer_root, (
            f"{name!r} resolved to {resolved}, outside {viewer_root}"
        )


@pytest.mark.parametrize("name", ["a/b", "a\\b", "../etc", "a b", "a;b", "a$b", ""])
def test_separators_and_odd_characters_remain_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        _normalize_project_name(name)


def test_length_limit_is_enforced() -> None:
    assert _normalize_project_name("a" * 128) == "a" * 128
    with pytest.raises(ValueError):
        _normalize_project_name("a" * 129)


def test_the_previously_escaping_name_no_longer_resolves() -> None:
    escaped = (PROJECT_ROOT / "viewer_data" / "local" / ".." / "viewer_config.local.json").resolve()
    assert escaped.parent == (PROJECT_ROOT / "viewer_data").resolve()
    assert resolve_viewer_project_config("..") is None
