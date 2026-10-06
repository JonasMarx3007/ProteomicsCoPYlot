"""The frontend's generated API types describe the backend as it is now.

frontend/src/lib/generated/openapi.json is the backend's OpenAPI schema;
api.d.ts is generated from it, and frontend/src/lib/apiContract.ts checks the
frontend's request types and value unions against it when `tsc` runs. If the
backend changes and the file is not regenerated, those checks run against an
old backend -- so this fails until `npm --prefix frontend run generate:api` is
run and the result committed.

plotLimits.json is the backend's plot size limits, which the frontend's size
controls clamp to (frontend/src/lib/plotLimits.ts reads it directly).

Together they replace tests that compared the two sides with regular
expressions over the TypeScript source.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ROOT / "frontend" / "src" / "lib" / "generated" / "openapi.json"


def _exporter():
    spec = importlib.util.spec_from_file_location("export_openapi", ROOT / "tools" / "export_openapi.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_schema_matches_the_backend() -> None:
    committed = json.loads(GENERATED.read_text(encoding="utf-8"))
    current = json.loads(_exporter().render())
    stale = sorted(set(committed["paths"]) ^ set(current["paths"]))
    assert committed == current, (
        "frontend/src/lib/generated/openapi.json is stale; run "
        f"`npm --prefix frontend run generate:api`. Routes that differ: {stale[:10]}"
    )



def test_the_committed_plot_limits_match_the_backend() -> None:
    """The size controls clamp to these; a stale copy offers sizes the backend refuses."""
    committed = (GENERATED.parent / "plotLimits.json").read_text(encoding="utf-8")
    assert committed == _exporter().render_limits(), (
        "frontend/src/lib/generated/plotLimits.json is stale; run "
        "`npm --prefix frontend run generate:api`"
    )


@pytest.mark.parametrize("frontend_built", [False, True])
def test_schema_is_independent_of_frontend_build(tmp_path, frontend_built):
    """A clean backend checkout and a packaged app expose the same API."""
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    if frontend_built:
        (frontend / "index.html").write_text("<!doctype html><title>Fixture</title>", encoding="utf-8")
    code = """
import runpy
from pathlib import Path
from unittest.mock import patch
is_file = Path.is_file
def frontend_file(path):
    if path.name == 'index.html' and not FRONTEND_BUILT:
        return False
    return is_file(path)
with patch.object(Path, 'is_file', frontend_file):
    module = runpy.run_path('tools/export_openapi.py')
    print(module['render']())
""".replace("FRONTEND_BUILT", repr(frontend_built))
    env = {**os.environ, "COPYLOT_FRONTEND_DIST": str(frontend)}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == json.loads(GENERATED.read_text(encoding="utf-8"))
