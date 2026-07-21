from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    # The repository has a local "build/" directory. Remove the project root
    # so "python -m build" resolves the installed PyPA build package.
    root_text = str(ROOT).lower()
    sys.path = [
        entry
        for entry in sys.path
        if entry and os.path.abspath(entry).lower() != root_text
    ]

    build_args = sys.argv[1:] or ["--sdist", "--wheel"]
    sys.argv = ["build", *build_args, str(ROOT)]
    runpy.run_module("build", run_name="__main__")


if __name__ == "__main__":
    main()
