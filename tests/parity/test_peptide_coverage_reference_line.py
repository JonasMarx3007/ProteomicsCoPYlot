"""The peptide/precursor coverage reference line is the union of the bars.

It counts sequences quantified in at least one annotated sample -- the same
definition the protein coverage plot uses -- not the number of sequences in the
file. Identified-but-never-quantified sequences and sequences quantified only
in runs outside the annotation used to lift the line above every bar.

Checked in all three implementations: backend, pip notebook, R notebook.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import pandas as pd  # noqa: E402
import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

RUNS = ["A1", "A2", "B1", "B2"]
UNSELECTED = "Z9"


def _report() -> pd.DataFrame:
    rows = []
    quantified = {"P1": RUNS, "P2": ["A1"], "P3": ["B2"]}  # 3 sequences seen in the selection
    for seq in ["P1", "P2", "P3", "P4_never", "P5_elsewhere"]:
        for run in RUNS + [UNSELECTED]:
            if seq in quantified and run in quantified[seq]:
                value = 100.0
            elif seq == "P5_elsewhere" and run == UNSELECTED:
                value = 100.0
            else:
                value = 0.0
            rows.append((run, seq, seq + "2", value))
    return pd.DataFrame(rows, columns=["File.Name", "Stripped.Sequence", "Precursor.Id", "Precursor.Quantity"])


EXPECTED_LINE = 3  # P1, P2, P3 -- not 5
EXPECTED_BARS = [1 + 1, 1, 1, 1 + 1]  # A1: P1+P2, A2: P1, B1: P1, B2: P1+P3


def _meta() -> pd.DataFrame:
    return pd.DataFrame({"sample": RUNS, "condition": ["A", "A", "B", "B"]})


def test_backend_line_is_the_union_of_the_bars(monkeypatch):
    from types import SimpleNamespace
    from app.services import peptide_tools, plot_images

    frame = _report()
    monkeypatch.setattr(peptide_tools, "get_peptide_frame", lambda: frame)
    monkeypatch.setattr(peptide_tools, "get_current_dataset", lambda _: None)
    monkeypatch.setattr(peptide_tools, "get_peptide_metadata", lambda: SimpleNamespace(frame=_meta()))
    for level in ("peptide", "precursor"):
        summary, count, _meta_out = plot_images._peptide_coverage_summary(level=level)
        assert summary["Value"].tolist() == EXPECTED_BARS
        assert count == EXPECTED_LINE

    captured = []
    monkeypatch.setattr(plot_images, "_to_png_bytes", lambda fig, plt, **kw: captured.append(fig) or b"")
    plot_images.qc_peptide_coverage_plot(level="peptide")
    ax = captured[-1].axes[0]
    lines = [line for line in ax.get_lines() if len(set(line.get_ydata())) == 1]
    assert [set(line.get_ydata()).pop() for line in lines] == [EXPECTED_LINE]


def _notebook():
    spec = importlib.util.spec_from_file_location(
        "notebook_functions", ROOT / "proteomicscopylot" / "notebook_functions.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pip_notebook_line_is_the_union_of_the_bars():
    notebook = _notebook()
    meta = _meta().assign(new_sample=RUNS)
    fig = notebook.coverage_plot_pep(_report(), meta, legend=False)
    ax = fig.axes[0]
    assert [patch.get_height() for patch in ax.patches] == EXPECTED_BARS
    lines = [line for line in ax.get_lines() if len(set(line.get_ydata())) == 1]
    assert [set(line.get_ydata()).pop() for line in lines] == [EXPECTED_LINE]


@pytest.mark.requires_r()
def test_r_notebook_line_is_the_union_of_the_bars(tmp_path):
    report_path = tmp_path / "report.tsv"
    _report().to_csv(report_path, sep="\t", index=False)
    script = f"""
      suppressMessages(source("proteomicscopylot/notebook_functions.R"))
      report <- read.delim("{report_path.as_posix()}", check.names = FALSE)
      meta <- data.frame(sample = c({", ".join(repr(r) for r in RUNS)}),
                         condition = c("A", "A", "B", "B"),
                         new_sample = c({", ".join(repr(r) for r in RUNS)}))
      grDevices::pdf(NULL)
      seen <- new.env()
      trace("barplot.default", where = asNamespace("graphics"), print = FALSE,
            tracer = quote(assign("heights", as.numeric(height), envir = seen)))
      # coverage_plot_pep is sourced into the global env, so a global segments()
      # shadows graphics::segments and records the reference line's height.
      segments <- function(x0, y0, x1, y1, ...) assign("line", y0, envir = seen)
      coverage_plot_pep(report, meta, legend = FALSE)
      stopifnot(identical(seen$heights, c({", ".join(str(float(b)) for b in EXPECTED_BARS)})))
      stopifnot(identical(as.numeric(seen$line), {float(EXPECTED_LINE)}))
      cat("OK\\n")
    """
    result = subprocess.run(
        ["Rscript", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=300
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
