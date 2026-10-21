"""The pip package must run without the GUI backend.

`proteomicscopylot` is installed on its own (`pip install proteomicscopylot`)
and used from notebooks; nothing in it may import from `backend/`, `app.`,
`tests/`, `frontend/` or any other part of this repository. The backend is
free to share code internally; the package is not allowed to reach into it.
These tests install the package's files alone, in a fresh interpreter that
cannot see the repository and refuses every forbidden import, and then import
and use it -- so a stray `from app.services... import` fails here before it
fails for a user who never cloned the repository.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "proteomicscopylot"
FORBIDDEN_PREFIXES = ("app", "backend", "tests", "frontend", "proteomics_backend")


# Run in a fresh interpreter: the package's own files are copied to a directory
# of their own, the interpreter starts isolated (-I: no PYTHONPATH, no current
# directory), and an import hook refuses every forbidden top-level name, so
# nothing from this checkout can stand in for a missing dependency.
STANDALONE_IMPORT = """
import importlib, pkgutil, sys
sys.path.insert(0, sys.argv[1])
FORBIDDEN = set(sys.argv[2].split(","))

class Refuse:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in FORBIDDEN:
            raise ImportError(f"the pip package imported {name}")
        return None

sys.meta_path.insert(0, Refuse())
import proteomicscopylot
names = ["proteomicscopylot"] + [
    info.name for info in pkgutil.walk_packages(proteomicscopylot.__path__, "proteomicscopylot.")
]
for name in names:
    importlib.import_module(name)
leaked = sorted(name for name in sys.modules if name.split(".")[0] in FORBIDDEN)
assert not leaked, leaked
print("IMPORTED", len(names))
"""


def test_no_package_module_imports_the_backend_or_the_repository(tmp_path):
    import shutil

    shutil.copytree(PACKAGE, tmp_path / "proteomicscopylot", ignore=shutil.ignore_patterns("__pycache__"))
    result = subprocess.run(
        [sys.executable, "-I", "-c", STANDALONE_IMPORT, str(tmp_path), ",".join(FORBIDDEN_PREFIXES)],
        cwd=tmp_path, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, "the pip package reaches into the repository:\n" + result.stderr[-2000:]
    assert "IMPORTED" in result.stdout


def test_the_wheel_ships_only_the_package():
    """setuptools packages: proteomicscopylot only -- never backend/app."""
    # Parse the isolated package metadata without importing the project.
    tomllib = pytest.importorskip("tomllib")

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    packages = config["tool"]["setuptools"]["packages"]
    assert all(name.split(".")[0] == "proteomicscopylot" for name in packages), packages
    assert not any(name.split(".")[0] in FORBIDDEN_PREFIXES for name in packages)


def test_notebook_functions_imports_with_the_backend_hidden(tmp_path):
    """Load the module in a fresh interpreter whose sys.path has no `backend/` and no repo root."""
    script = f"""
import sys
sys.path = [p for p in sys.path if not p.rstrip('/\\\\').endswith(('backend', 'ProteomicsCoPYlot', 'repo'))]
sys.modules['app'] = None  # any `import app...` now raises ImportError
import importlib.util
spec = importlib.util.spec_from_file_location('notebook_functions', {str(PACKAGE / 'notebook_functions.py')!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert callable(module.volcano_data_f) and callable(module.quantile_normalize)
print('STANDALONE-OK')
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr
    assert "STANDALONE-OK" in result.stdout
