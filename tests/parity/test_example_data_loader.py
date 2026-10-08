"""`load_example_data` reads the same bundled files in the pip package and the R functions."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from _r_runtime import RSCRIPT
from proteomicscopylot import notebook_functions as nb

ROOT = Path(__file__).resolve().parents[2]


def test_every_example_name_loads_in_python() -> None:
    for name in nb.EXAMPLE_DATA_FILES:
        frame = nb.load_example_data(name)
        assert len(frame) > 0, name
    with pytest.raises(ValueError, match="Unknown example"):
        nb.example_data_path("proteins")


@pytest.mark.requires_r("jsonlite")
def test_r_loads_the_same_examples() -> None:
    script = """
      source(file.path("proteomicscopylot", "notebook_functions.R"))
      shapes <- lapply(names(EXAMPLE_DATA_FILES), function(name) dim(load_example_data(name)))
      names(shapes) <- names(EXAMPLE_DATA_FILES)
      cat(jsonlite::toJSON(list(files = as.list(EXAMPLE_DATA_FILES), shapes = shapes), auto_unbox = TRUE))
    """
    completed = subprocess.run([RSCRIPT, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["files"] == nb.EXAMPLE_DATA_FILES
    for name, shape in payload["shapes"].items():
        assert list(nb.load_example_data(name).shape) == shape, name
