"""The control volcano needs four distinct conditions in every implementation.

With one control shared by both sides the fold change reduces to
condition1 - condition2, but the control's variance enters the standard error
twice: raw p < 0.05 fell to 1.3 % of null rows instead of 5 %. The web app has
always refused this design; the pip and R packages accepted it and so gave a
different answer for the same request. All three now refuse it with one message.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from proteomicscopylot import notebook_functions as notebook

ROOT = Path(__file__).resolve().parents[2]
MESSAGE = ("Control-corrected volcano analysis requires four distinct conditions; "
           "an experimental condition cannot be used as its own control.")
SAMPLES = [f"{c}{i}" for c in "ABCD" for i in range(1, 4)]


def _data():
    rng = np.random.default_rng(3)
    frame = pd.DataFrame(rng.normal(20, 1, (20, len(SAMPLES))), columns=SAMPLES)
    frame.insert(0, "ProteinNames", [f"P{i}" for i in range(20)])
    return frame, pd.DataFrame({"sample": SAMPLES, "condition": [s[0] for s in SAMPLES]})


@pytest.mark.parametrize("controls", [("C", "C"), ("A", "D"), ("C", "B")])
def test_pip_refuses_a_shared_or_reused_condition(controls):
    frame, meta = _data()
    with pytest.raises(ValueError) as error:
        notebook.volcano_data_f_control(frame, meta, "A", "B", *controls)
    assert str(error.value) == MESSAGE


def test_pip_accepts_four_distinct_conditions():
    frame, meta = _data()
    assert len(notebook.volcano_data_f_control(frame, meta, "A", "B", "C", "D")) == 20


@pytest.mark.requires_r()
def test_r_refuses_a_shared_control_with_the_same_message(tmp_path):
    from app.services.r_runtime import detect_r_runtime

    runtime = detect_r_runtime()
    frame, meta = _data()
    frame.to_csv(tmp_path / "data.csv", index=False)
    meta.to_csv(tmp_path / "meta.csv", index=False)
    script = f"""
    suppressPackageStartupMessages(source("{(ROOT / 'proteomicscopylot' / 'notebook_functions.R').as_posix()}"))
    data <- read.csv("{(tmp_path / 'data.csv').as_posix()}", check.names = FALSE)
    meta <- read.csv("{(tmp_path / 'meta.csv').as_posix()}", check.names = FALSE)
    shared <- tryCatch({{ volcano_data_f_control(data, meta, "A", "B", "C", "C"); "accepted" }},
                       error = function(e) conditionMessage(e))
    distinct <- nrow(volcano_data_f_control(data, meta, "A", "B", "C", "D"))
    writeLines(c(shared, as.character(distinct)), "{(tmp_path / 'out.txt').as_posix()}")
    """
    completed = subprocess.run([str(runtime["executable"]), "-e", script], capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr[-2000:]
    shared, distinct = (tmp_path / "out.txt").read_text(encoding="utf-8").splitlines()
    assert shared == MESSAGE
    assert distinct == "20"
