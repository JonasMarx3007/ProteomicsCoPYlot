from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent

# The repository has a local "build/" directory. Remove the project root from
# module resolution so "python -m build" resolves the PyPA build package.
root_text = str(ROOT).lower()
sys.path = [
    entry
    for entry in sys.path
    if entry and os.path.abspath(entry).lower() != root_text
]

sys.argv = ["build", "--sdist", "--wheel", str(ROOT)]
runpy.run_module("build", run_name="__main__")

