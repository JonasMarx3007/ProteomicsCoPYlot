"""A viewer backend must not serve the analysis bundle.

The analysis and viewer UIs are two builds of the same source, separated only by
`VITE_APP_MODE`, which is baked in and invisible afterwards. Every viewer gate in
`App.tsx` hangs off `IS_VIEWER_MODE`, so serving the analysis bundle from the
viewer launcher produces a viewer with **no gating at all**: Upload, Imputation,
Restore, ID Translator, peptide collapse, simulation and the phospho pipeline all
on screen, over read-only data, with nothing saying the gating is not running.

That is exactly what happened: `launch_viewer.py` serves whatever prebuilt bundle
is in `frontend/dist`, a plain `npm run build` writes the analysis bundle there,
and the viewer came up ungated. The backend still refused writes, so the only
symptom was a UI offering things it should not.

`vite.config.ts` now writes the mode into the bundle and the launcher refuses the
mismatch instead of serving it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

import launch

PACKAGING = ROOT / "packaging"


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """A dist directory the launcher will look at."""

    def build(mode: str | None) -> Path:
        dist = tmp_path / "dist"
        dist.mkdir(exist_ok=True)
        (dist / "index.html").write_text("<html></html>", encoding="utf-8")
        if mode is not None:
            (dist / "build-mode.json").write_text(
                json.dumps({"appMode": mode, "aiEnabled": False}), encoding="utf-8"
            )
        monkeypatch.setenv("COPYLOT_FRONTEND_DIST", str(dist))
        return dist

    return build


# --- the mismatch is refused, in both directions ------------------------------


def test_the_viewer_launcher_refuses_an_analysis_bundle(bundle) -> None:
    """The failure this exists for."""
    bundle("analysis")
    with pytest.raises(ValueError) as exc:
        launch.check_frontend_bundle_mode(viewer=True)
    message = str(exc.value)
    assert "analysis" in message and "viewer" in message
    assert "VITE_APP_MODE=viewer" in message, "the error should name the fix"


def test_the_analysis_launcher_refuses_a_viewer_bundle(bundle) -> None:
    """The same mistake the other way round cripples the tool instead."""
    bundle("viewer")
    with pytest.raises(ValueError, match="built for viewer mode"):
        launch.check_frontend_bundle_mode(viewer=False)


@pytest.mark.parametrize("viewer", [True, False])
def test_a_matching_bundle_passes_without_a_word(bundle, viewer: bool) -> None:
    bundle("viewer" if viewer else "analysis")
    assert launch.check_frontend_bundle_mode(viewer=viewer) is None


# --- what cannot be checked is said, not guessed -------------------------------


@pytest.mark.parametrize("viewer", [True, False])
def test_a_bundle_without_the_marker_warns_rather_than_blocking(bundle, viewer: bool) -> None:
    """A bundle built before the marker existed is unknown, not wrong.

    Refusing it would strand anyone with an older build; claiming it is fine
    would be the silence this whole change is about.
    """
    bundle(None)
    warning = launch.check_frontend_bundle_mode(viewer=viewer)
    assert warning and "build-mode.json" in warning
    assert f"VITE_APP_MODE={'viewer' if viewer else 'analysis'}" in warning


def test_an_unreadable_marker_is_treated_as_unknown(bundle) -> None:
    dist = bundle("viewer")
    (dist / "build-mode.json").write_text("{not json", encoding="utf-8")
    assert launch.frontend_bundle_mode(dist) is None


def test_an_unrecognised_mode_is_not_taken_at_its_word(bundle) -> None:
    dist = bundle("something-else")
    assert launch.frontend_bundle_mode(dist) is None


def test_no_configured_bundle_is_not_an_error(monkeypatch) -> None:
    """The launcher can run without a built frontend; that is a separate story."""
    monkeypatch.delenv("COPYLOT_FRONTEND_DIST", raising=False)
    assert launch.check_frontend_bundle_mode(viewer=True) is None
    assert os.getenv("COPYLOT_FRONTEND_DIST") is None


# --- the build actually writes the marker --------------------------------------
#
# That vite.config.ts emits build-mode.json, and spells the mode exactly as
# src/lib/appMode.ts reads it, is tested by running the build plugin and the
# module under each spelling: frontend/tests/unit/frontend-bundle-mode.test.ts.


# --- the launchers that set the mode -------------------------------------------


@pytest.mark.parametrize(
    "script",
    [
        "windows/run_viewer.bat",
        "windows/run_viewer_ai.bat",
        "linux/run_viewer_linux.sh",
        "linux/run_viewer_ai_linux.sh",
        "macos/run_viewer_macos.sh",
        "macos/run_viewer_ai_macos.sh",
    ],
)
def test_every_viewer_launcher_sets_viewer_mode(script: str) -> None:
    """These are the scripts that get this right; they must keep doing so."""
    path = PACKAGING / script
    if not path.is_file():
        pytest.skip(f"{script} is not part of this checkout")
    assert "VITE_APP_MODE=viewer" in path.read_text(encoding="utf-8"), (
        f"{script} starts a frontend without putting it in viewer mode"
    )


# --- the environment selects viewer mode too ------------------------------------


@pytest.mark.parametrize(
    ("flag", "env", "expected"),
    [(False, None, False), (True, None, True), (False, "1", True), (False, "0", False), (True, "0", True)],
)
def test_viewer_mode_is_requested_by_flag_or_environment(monkeypatch, flag, env, expected) -> None:
    """The Docker viewers pass no flag; COPYLOT_VIEWER_MODE=1 selects the viewer."""
    if env is None:
        monkeypatch.delenv("COPYLOT_VIEWER_MODE", raising=False)
    else:
        monkeypatch.setenv("COPYLOT_VIEWER_MODE", env)
    assert launch.viewer_mode_requested(flag) is expected


def test_an_environment_selected_viewer_accepts_the_viewer_bundle(bundle, monkeypatch) -> None:
    """How the container starts: `launch.py` with no flags and the env set."""
    bundle("viewer")
    monkeypatch.setenv("COPYLOT_VIEWER_MODE", "1")
    assert launch.check_frontend_bundle_mode(launch.viewer_mode_requested(False)) is None
