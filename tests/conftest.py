from __future__ import annotations

import os
import tempfile
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path

import pytest

os.environ["COPYLOT_TOOL_ACCESS_ENABLED"] = "0"
os.environ["COPYLOT_VIEWER_PORTAL_ENABLED"] = "0"
os.environ["COPYLOT_SESSION_ISOLATION"] = "0"
os.environ["COPYLOT_ALLOWED_HOSTS"] = "testserver"

import matplotlib

matplotlib.use("Agg")

import plotly.io

plotly.io.renderers.default = "plotly_mimetype"

_HEADLESS_RPROFILE = Path(tempfile.gettempdir()) / "copylot_headless_rprofile.R"
_HEADLESS_RPROFILE.write_text(
    "options(device = function(...) grDevices::pdf(NULL))\n"
    "options(browser = function(...) invisible(NULL))\n",
    encoding="utf-8",
)
os.environ["R_PROFILE_USER"] = str(_HEADLESS_RPROFILE)


# --- R ---------------------------------------------------------------------
# Tests that run R are marked `@pytest.mark.requires_r("pkg", ...)`, naming the
# R packages they need beyond base R. Without Rscript or one of the packages the
# test is skipped with a reason naming what is missing -- unless
# COPYLOT_REQUIRE_R=1 (set in CI on the runners that install R), where a missing
# piece fails the test instead of quietly skipping it.
R_REQUIRED = os.environ.get("COPYLOT_REQUIRE_R", "").strip() == "1"


def r_executable() -> str | None:
    from app.services.r_runtime import detect_r_runtime

    runtime = detect_r_runtime()
    return str(runtime["executable"]) if runtime.get("available") else None


_R_PACKAGE_CACHE: dict[str, bool] = {}


def _missing_r_packages(executable: str, packages: tuple[str, ...]) -> list[str]:
    import subprocess

    unknown = [name for name in packages if name not in _R_PACKAGE_CACHE]
    if unknown:
        script = "for (p in commandArgs(TRUE)) cat(p, requireNamespace(p, quietly = TRUE), '\\n')"
        result = subprocess.run([executable, "-e", script, "--args", *unknown],
                                capture_output=True, text=True, timeout=120)
        found = dict(line.split() for line in result.stdout.splitlines() if len(line.split()) == 2)
        for name in unknown:
            _R_PACKAGE_CACHE[name] = found.get(name) == "TRUE"
    return [name for name in packages if not _R_PACKAGE_CACHE[name]]


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_r(*packages): runs Rscript with these R packages; skipped when they are "
        "missing, failed instead when COPYLOT_REQUIRE_R=1",
    )


# Each top-level test folder is also a marker, so `-m parity` or `-m "not
# integration"` selects across folders without listing paths.
_FOLDER_MARKERS = ("unit", "reference", "integration", "parity", "contracts", "repo")


def pytest_collection_modifyitems(config, items):
    tests_dir = Path(__file__).resolve().parent
    for item in items:
        try:
            folder = Path(str(item.path)).resolve().relative_to(tests_dir).parts[0]
        except ValueError:
            continue
        if folder in _FOLDER_MARKERS:
            item.add_marker(getattr(pytest.mark, folder))


def _require_r(packages: tuple[str, ...]) -> str:
    executable = r_executable()
    if executable is None:
        missing = "Rscript"
    else:
        missing = ", ".join(f"R package {name}" for name in _missing_r_packages(executable, packages))
    if missing:
        if R_REQUIRED:
            pytest.fail(f"COPYLOT_REQUIRE_R=1 but {missing} is not available", pytrace=False)
        pytest.skip(f"{missing} is not available")
    return executable


def pytest_runtest_setup(item):
    marker = item.get_closest_marker("requires_r")
    if marker is not None:
        _require_r(tuple(marker.args))


@pytest.fixture
def rscript(request) -> str:
    """The Rscript executable, for a test marked `requires_r`."""
    marker = request.node.get_closest_marker("requires_r")
    return _require_r(tuple(marker.args) if marker else ())


@pytest.fixture(scope="session")
def require_r():
    """For fixtures, which cannot carry a marker: `require_r("pkg")` -> Rscript path."""
    return lambda *packages: _require_r(packages)


@pytest.fixture(scope="module", autouse=True)
def preserve_analysis_state_between_modules():
    """Viewer fixtures may share state within a module, never with the next one.

    Use the same store snapshots as atomic restore, including active
    packages/profiles. ExitStack restores them even if setup or a test fails.
    Imports are delayed until collection has established the backend path.
    """
    from app.services import restore_state

    with ExitStack() as cleanup:
        # The phosphosite localization cutoff is session state too: a module
        # that sets it would otherwise hide sites from every module after it.
        for store in ("dataset", "metadata", "annotation", "condition_palette", "peptide_metadata",
                      "localization_cutoff"):
            # Production snapshots are references intended for atomic replacement;
            # tests can mutate stores in place, so detach the saved state here.
            snapshot = deepcopy(getattr(restore_state, f"snapshot_{store}_session_state")())
            cleanup.callback(getattr(restore_state, f"restore_{store}_session_state"), snapshot)
        yield


# --- shared fixtures (moved from tests/backend/conftest.py, 2026-10-02) -------


@pytest.fixture(autouse=True)
def fresh_runtime_cache():
    """Each test computes its own results.

    The renderers are cached per cache version, session and arguments. In the
    application a new upload, filter or imputation bumps that version, so a
    stale figure cannot be served. A test that patches a module internal and
    calls the same renderer again changes neither the version nor the
    arguments, so it would be answered from the previous test's cache -- which
    is what happened when the render facade in functions.py was removed and the
    cache moved down to the modules themselves.
    """
    from app.services.runtime_cache import invalidate_runtime_cache

    invalidate_runtime_cache("test-start", all_sessions=True)
    yield
    invalidate_runtime_cache("test-end", all_sessions=True)


@pytest.fixture
def qc_protein_data():
    """A small annotated protein matrix the real QC routes can draw.

    Two conditions of three samples, one missing value and one clear outlier, so
    every QC plot has something to show: the boxplot draws a flier, coverage a
    gap. Route tests use this instead of replacing the renderer, so they keep
    checking the drawing that users get when the routing behind them changes.
    The module-level store snapshot in tests/conftest.py undoes the load.
    """
    import numpy as np
    import pandas as pd

    from app.schemas.annotation import AnnotationFilterConfig
    from app.services.annotation_store import save_annotation
    from app.services.dataset_store import save_table_dataset

    rng = np.random.default_rng(3)
    samples = [f"sample_{condition}_{index:02d}" for condition in "AB" for index in range(1, 4)]
    frame = pd.DataFrame({"ProteinNames": [f"P{index}" for index in range(30)],
                          **{sample: rng.normal(20.0, 1.0, 30) for sample in samples}})
    frame.loc[2, samples[0]] = np.nan
    frame.loc[5, samples[1]] = 35.0
    metadata = pd.DataFrame({"sample": samples, "condition": ["A"] * 3 + ["B"] * 3})
    save_table_dataset(filename="qc_routes.tsv", kind="protein", frame=frame)
    save_annotation(kind="protein", source_data=frame, metadata=metadata, log2_data=frame,
                    filtered_data=frame, is_log2_transformed=True, metadata_source="manual",
                    filter_config=AnnotationFilterConfig(), auto_detected=False, warnings=[],
                    log2_auto_detected=False)
    return frame, metadata


EXAMPLE_CONFIG = Path(__file__).resolve().parent / "fixtures" / "viewer_config.json"


@pytest.fixture(scope="module")
def example_project():
    """The bundled HEK293 example, loaded through the tests' own config.

    `tests/fixtures/viewer_config.json`, not the shipped one, so editing the demo
    does not change the tests. The module-level store snapshot above undoes it.
    """
    from app.services.viewer_bootstrap import load_viewer_state

    return load_viewer_state(EXAMPLE_CONFIG)


@pytest.fixture(scope="module")
def client(example_project):
    """A TestClient on the example project. A module may define its own `client`."""
    from fastapi.testclient import TestClient

    from app.main import app

    # The default TestClient host, `testserver`, is only allowed because the
    # environment above says so; `localhost` is what a browser sends.
    with TestClient(app, base_url="http://localhost") as test_client:
        yield test_client
