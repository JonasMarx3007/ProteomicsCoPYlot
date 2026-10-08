from __future__ import annotations

import contextlib
import io
import json
import sys
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "examples" / "example.ipynb"


def _code_cells() -> list[str]:
    payload = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return [
        "".join(cell["source"])
        for cell in payload["cells"]
        if cell.get("cell_type") == "code" and "".join(cell["source"]).strip()
    ]


def test_the_example_notebook_exists_and_has_code() -> None:
    assert NOTEBOOK.exists(), NOTEBOOK
    cells = _code_cells()
    assert len(cells) > 30, f"only {len(cells)} code cells found; has the notebook changed shape?"


@pytest.mark.slow
def test_every_cell_of_the_example_notebook_executes() -> None:
    import matplotlib

    matplotlib.use("Agg")

    previous = sys.path[:]
    namespace: dict[str, object] = {"__name__": "__main__"}
    failures: list[str] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for index, source in enumerate(_code_cells()):
                try:
                    with contextlib.redirect_stdout(io.StringIO()):
                        exec(compile(source, f"<example.ipynb cell {index}>", "exec"), namespace)
                except Exception as exc:
                    failures.append(f"cell {index}: {type(exc).__name__}: {exc}")
    finally:
        sys.path[:] = previous

    assert not failures, (
        "the published example notebook no longer runs against the package:\n  "
        + "\n  ".join(failures[:8])
    )


EXAMPLE_R = ROOT / "examples" / "example.R"


from _r_runtime import RSCRIPT


def test_the_r_example_exists() -> None:
    assert EXAMPLE_R.exists(), EXAMPLE_R


@pytest.mark.slow
@pytest.mark.requires_r("plotly")  # the example draws volcano plots
def test_the_r_example_runs(tmp_path) -> None:
    import subprocess

    completed = subprocess.run(
        [RSCRIPT, str(EXAMPLE_R)],
        capture_output=True,
        text=True,
        timeout=900,
        cwd=str(tmp_path),
    )
    if completed.returncode != 0:
        detail = [
            line.strip()
            for line in (completed.stderr or completed.stdout or "").splitlines()
            if line.strip() and "wurde unter R Version" not in line
        ]
        pytest.fail(
            "the published R example no longer runs against the package:\n  "
            + "\n  ".join(detail[-8:])
        )
