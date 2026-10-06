"""Compare displayed QC values, not just matching function names or signatures."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]

from app.services import peptide_tools
from app.services.functions import raw_zero_to_nan
from app.services.plot_images import _feature_context
from app.services.r_runtime import detect_r_runtime
from app.services.table_functions import prepare_coverage_df
from proteomicscopylot import notebook_functions as notebook


def r_output(script):
    executable = detect_r_runtime()["executable"]
    source = json.dumps((ROOT / "proteomicscopylot/notebook_functions.R").as_posix())
    result = subprocess.run(
        [executable, "--vanilla", "-e", f"source({source})\npdf(file=NULL)\n{script}\ndev.off()"],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return [line.removeprefix("VALUE:") for line in result.stdout.splitlines() if line.startswith("VALUE:")]


@pytest.mark.parametrize("key", ["ProteinNames", "Phosphoprotein", "PTM_Collapse_key"])
@pytest.mark.parametrize("scale,expected", [("log2", 2), ("linear", 1)])
@pytest.mark.requires_r()
def test_coverage_display_agrees_across_pipelines(key, scale, expected):
    frame = pd.DataFrame({key: ["a", "b", "c"], "A1": [0, 2, np.nan], "A2": [0, np.nan, np.nan], "unused": [1, 1, 1]})
    meta = pd.DataFrame({"sample": ["A1", "A2"], "condition": ["A", "A"]})
    gui_frame = frame.copy()
    if scale == "linear":
        gui_frame = raw_zero_to_nan(gui_frame, meta["sample"].tolist())
    gui = prepare_coverage_df(gui_frame, meta.copy())
    assert gui.loc[gui.Sample == "All samples", "Number"].item() == expected
    assert _feature_context(gui_frame, meta["sample"].tolist())[2] == expected
    for function in (notebook.coverage_plot, notebook.coverage_plot_summary):
        for header in (True, False):
            fig = function(frame.copy(), meta.copy(), data_scale=scale, header=header)
            try:
                references = [line for line in fig.axes[0].lines if line.get_color() == "red"]
                assert len(references) == 1
                assert list(references[0].get_ydata()) == [expected, expected]
            finally:
                plt.close(fig)
    values = r_output(f'''
        d <- data.frame(feature=c("a","b","c"), A1=c(0,2,NA), A2=c(0,NA,NA), unused=c(1,1,1))
        names(d)[1] <- "{key}"
        meta <- data.frame(sample=c("A1","A2"), condition=c("A","A"))
        segments <- function(x0,y0,x1,y1,...) {{
            cat("VALUE:", y0, "\\n", sep="")
            graphics::segments(x0,y0,x1,y1,...)
        }}
        for (f in list(coverage_plot, coverage_plot_summary)) {{
            for (header in c(TRUE,FALSE)) f(d,meta,header=header,data_scale="{scale}")
        }}
    ''')
    assert values == [str(expected)] * 4


@pytest.mark.parametrize("sequences,expected", [
    (["PEPTIDEK", "AAAKAAAR", "AAKAARAAR", "GGKGGRGGKGGR"], "75.0%"),
    (["PEPTIDEK"], "0.0%"),
    (["AAKAARAAR"], "100.0%"),
    (["PEPTIDEK", "AAKAARAAR"], "50.0%"),
])
@pytest.mark.parametrize("show_text", [True, False])
@pytest.mark.requires_r()
def test_missed_cleavage_display_agrees_across_pipelines(monkeypatch, sequences, expected, show_text):
    runs = ["run_1.raw", "run_2.raw"]
    meta = pd.DataFrame({"sample": runs, "condition": ["ctrl", "treat"]})
    frame = pd.DataFrame([
        {"File.Name": run, "Modified.Sequence": sequence, "Stripped.Sequence": sequence, "Precursor.Quantity": 1000.0}
        for run in runs for sequence in sequences
    ])
    wanted = [expected] * 2 if show_text else []
    monkeypatch.setattr(notebook, "read_data", lambda _: frame.copy())
    fig = notebook.missed_cleavage_plot("fixture.tsv", meta.copy(), text=show_text)
    try:
        assert [label.get_text() for label in fig.axes[0].texts] == wanted
    finally:
        plt.close(fig)
    captured = []

    def capture(fig, plt, **kwargs):
        captured.extend(label.get_text() for label in fig.axes[0].texts)
        plt.close(fig)
        return b"png"

    monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: frame.copy())
    monkeypatch.setattr(peptide_tools, "get_peptide_metadata", lambda: SimpleNamespace(frame=meta.copy(), empty=False))
    monkeypatch.setattr(peptide_tools, "get_current_dataset", lambda *args: None)
    monkeypatch.setattr(peptide_tools, "_to_png_bytes", capture)
    peptide_tools.peptide_missed_cleavage_plot(text=show_text)
    assert captured == wanted
    r_sequences = ",".join(json.dumps(sequence) for sequence in sequences)
    values = r_output(f'''
        peptides <- expand.grid(Stripped.Sequence=c({r_sequences}), File.Name=c("run_1.raw","run_2.raw"), stringsAsFactors=FALSE)
        peptides$Modified.Sequence <- peptides$Stripped.Sequence
        peptides$Precursor.Quantity <- 1000
        read_data <- function(...) peptides
        meta <- data.frame(sample=c("run_1.raw","run_2.raw"), condition=c("ctrl","treat"))
        text <- function(x,y,labels,...) {{
            for (label in labels) cat("VALUE:", label, "\\n", sep="")
            graphics::text(x,y,labels,...)
        }}
        missed_cleavage_plot("fixture.tsv",meta,text={str(show_text).upper()})
    ''')
    assert values == wanted
