"""The pip package must run without the GUI backend.

`proteomicscopylot` is installed on its own (`pip install proteomicscopylot`)
and used from notebooks; nothing in it may import from `backend/`, `app.`,
`tests/`, `frontend/` or any other part of this repository. The backend is
free to share code internally; the package is not allowed to reach into it.
This test reads the import statements rather than trusting the environment,
so a stray `from app.services... import` fails here before it fails for a
user who never cloned the repository.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "proteomicscopylot"
FORBIDDEN_PREFIXES = ("app", "backend", "tests", "frontend", "proteomics_backend")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_no_package_module_imports_the_backend_or_the_repository():
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        for name in sorted(_imported_modules(path)):
            root = name.split(".")[0]
            if root in FORBIDDEN_PREFIXES:
                offenders.append(f"{path.relative_to(ROOT)}: import {name}")
    assert not offenders, "the pip package reaches into the repository:\n" + "\n".join(offenders)


def test_the_wheel_ships_only_the_package():
    """setuptools packages: proteomicscopylot only -- never backend/app."""
    import tomllib

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
